"""Site-to-scraper preference memory for scrape backend ordering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .state_store import StateStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def site_key(url: str) -> str:
    parsed = urlparse(str(url))
    host = (parsed.netloc or "").lower().split("@").pop().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    path_parts = [part for part in parsed.path.split("/") if part]
    if host == "github.com" and len(path_parts) >= 2:
        if len(path_parts) >= 3 and path_parts[2] in {"issues", "pull", "discussions"}:
            return f"github.com/{path_parts[2]}"
        return "github.com/repo"
    if host in {"reddit.com", "old.reddit.com"} or host.endswith(".reddit.com"):
        return host
    if host.endswith("zhihu.com"):
        return "zhihu.com"
    return host or "unknown"


@dataclass
class ScrapeAttempt:
    url: str
    scraper: str
    success: bool
    content_length: int = 0
    error_type: str = ""
    error_message: str = ""
    elapsed_ms: int | None = None


class SiteScraperMemory:
    def __init__(self, store: StateStore | None = None, min_success_chars: int = 300):
        self.store = store or StateStore()
        self.min_success_chars = min_success_chars
        self._updates: list[dict] = []

    def reorder_backends(self, url: str, backends: list[str] | tuple[str, ...]) -> list[str]:
        original = list(backends)
        site = site_key(url)
        rows = self.store.rows(
            "SELECT * FROM site_scraper_stats WHERE site = ?",
            (site,),
        )
        by_scraper = {row["scraper"]: row for row in rows}
        now = _now()

        def rank(scraper: str) -> tuple:
            row = by_scraper.get(scraper)
            original_index = original.index(scraper)
            if not row:
                return (2, 0, 0, original_index)
            cooldown = _parse_iso(row.get("cooldown_until"))
            in_cooldown = bool(cooldown and cooldown > now)
            manual = 0 if row.get("manually_pinned") else 1
            manual_priority = row.get("manual_priority")
            priority = int(manual_priority) if manual_priority is not None else 100
            successes = int(row.get("success_count") or 0)
            failures = int(row.get("failure_count") or 0) + int(row.get("blocked_count") or 0) + int(row.get("timeout_count") or 0)
            score = successes - failures
            return (1 if in_cooldown else manual, priority, -score, original_index)

        return sorted(original, key=rank)

    def record_attempt(self, attempt: ScrapeAttempt) -> None:
        site = site_key(attempt.url)
        now = _iso()
        error_type = attempt.error_type or classify_scrape_error(attempt.error_message)
        success = bool(attempt.success and attempt.content_length >= self.min_success_chars)
        self.store.execute(
            """
            INSERT INTO scrape_attempts (
                url, site, scraper, success, content_length, error_type,
                error_message, elapsed_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.url, site, attempt.scraper, 1 if success else 0,
                attempt.content_length, error_type, attempt.error_message,
                attempt.elapsed_ms, now,
            ),
        )
        self._ensure_row(site, attempt.scraper)
        if success:
            self.store.execute(
                """
                UPDATE site_scraper_stats
                SET success_count = success_count + 1,
                    avg_content_length = CASE
                      WHEN avg_content_length IS NULL THEN ?
                      ELSE CAST(((avg_content_length * success_count) + ?) / (success_count + 1) AS INTEGER)
                    END,
                    last_success_at = ?, last_error_type = NULL, last_error_message = NULL,
                    cooldown_until = NULL, sample_url = ?, updated_at = ?
                WHERE site = ? AND scraper = ?
                """,
                (attempt.content_length, attempt.content_length, now, attempt.url, now, site, attempt.scraper),
            )
        else:
            failure_col = "failure_count"
            if error_type == "blocked":
                failure_col = "blocked_count"
            elif error_type == "timeout":
                failure_col = "timeout_count"
            cooldown_until = _iso(_now() + timedelta(hours=1)) if error_type in {"blocked", "timeout"} else None
            self.store.execute(
                f"""
                UPDATE site_scraper_stats
                SET {failure_col} = {failure_col} + 1,
                    last_failure_at = ?, last_error_type = ?, last_error_message = ?,
                    cooldown_until = COALESCE(?, cooldown_until), sample_url = ?, updated_at = ?
                WHERE site = ? AND scraper = ?
                """,
                (now, error_type, attempt.error_message, cooldown_until, attempt.url, now, site, attempt.scraper),
            )
        self._updates.append({
            "site": site,
            "scraper": attempt.scraper,
            "success": success,
            "content_length": attempt.content_length,
            "error_type": "" if success else error_type,
        })

    def stats(self, site: str | None = None) -> list[dict]:
        if site:
            return self.store.rows(
                "SELECT * FROM site_scraper_stats WHERE site = ? ORDER BY manually_pinned DESC, success_count DESC, scraper",
                (site,),
            )
        return self.store.rows(
            "SELECT * FROM site_scraper_stats ORDER BY site, manually_pinned DESC, success_count DESC, scraper"
        )

    def set_preference(self, site: str, scraper: str, priority: int | None = None, note: str | None = None) -> None:
        self._ensure_row(site, scraper)
        now = _iso()
        self.store.execute(
            """
            UPDATE site_scraper_stats
            SET manually_pinned = 1, manual_priority = ?, last_error_message = COALESCE(?, last_error_message), updated_at = ?
            WHERE site = ? AND scraper = ?
            """,
            (priority if priority is not None else 0, note, now, site, scraper),
        )

    def reset(self, site: str | None = None) -> int:
        if site:
            with self.store.connect() as conn:
                cur = conn.execute("DELETE FROM site_scraper_stats WHERE site = ?", (site,))
                conn.execute("DELETE FROM scrape_attempts WHERE site = ?", (site,))
                return int(cur.rowcount or 0)
        with self.store.connect() as conn:
            cur = conn.execute("DELETE FROM site_scraper_stats")
            conn.execute("DELETE FROM scrape_attempts")
            return int(cur.rowcount or 0)

    def consume_updates(self) -> list[dict]:
        updates = list(self._updates)
        self._updates.clear()
        return updates

    def _ensure_row(self, site: str, scraper: str) -> None:
        now = _iso()
        self.store.execute(
            """
            INSERT OR IGNORE INTO site_scraper_stats (
                site, scraper, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (site, scraper, now, now),
        )


def classify_scrape_error(message: str) -> str:
    text = str(message or "").lower()
    if "blocked" in text or "login" in text or "captcha" in text or "荒原" in text:
        return "blocked"
    if "timeout" in text or "deadline" in text:
        return "timeout"
    if "rate limit" in text or "429" in text:
        return "rate_limit"
    return "error"
