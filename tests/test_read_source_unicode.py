import hashlib
import io
import json
import socket
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp import cli, tools
from multi_search_mcp.src import service
from multi_search_mcp.src.service import ReadSourceRequest, run_read_source
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.state_store import StateStore


class ReadSourceUnicodeTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = StateStore(Path(directory.name) / "state.sqlite")
        self.cache = ContentStore(self.store)
        for target in (
            mock.patch.object(socket.socket, "connect"),
            mock.patch.object(service, "scrape_url_smart"),
            mock.patch.object(service, "load_keys"),
        ):
            blocked = target.start()
            blocked.side_effect = AssertionError("cached reads must not fetch or load keys")
            self.addCleanup(target.stop)

    def test_keyword_after_expanding_lowercase_uses_original_offset(self):
        self.cache.put("src_unicode", "İ target evidence")

        response = run_read_source(
            ReadSourceRequest("src_unicode", keyword="target", limit=6),
            state_store=self.store,
        )

        self.assertEqual(response["match_offset"], 2)
        self.assertEqual(response["start"], 2)
        self.assertEqual(response["end"], 8)
        self.assertEqual(response["content"], "target")

    def test_unicode_matching_preserves_lowercase_semantics_and_original_text(self):
        cases = (
            ("İİ 中文 ÉVIDENCE", "évidence", 6, "ÉVIDENCE"),
            ("İ target TARGET", "TARGET", 2, "target"),
            ("İ İSTANBUL", "i\u0307stanbul", 2, "İSTANBUL"),
            ("İ i\u0307stanbul", "İSTANBUL", 2, "i\u0307stanbul"),
            ("İ ΟΣ", "ος", 2, "ΟΣ"),
            ("İ Straße", "STRAẞE", 2, "Straße"),
            ("İ", "\u0307", 0, "İ"),
        )
        for body, keyword, start, content in cases:
            with self.subTest(body=body, keyword=keyword):
                self.cache.put("src_unicode", body)
                response = run_read_source(
                    ReadSourceRequest("src_unicode", keyword=keyword, limit=len(content)),
                    state_store=self.store,
                )
                self.assertEqual(response["match_offset"], start)
                self.assertEqual(response["start"], start)
                self.assertEqual(response["end"], start + len(content))
                self.assertEqual(response["content"], content)
                self.assertEqual(response["content_length"], len(body))

    def test_keywords_remain_literal(self):
        for keyword in ("(a)", "[b]", "a.b", "[", ".*", r"\b", "^$|?+{2}"):
            with self.subTest(keyword=keyword):
                body = "İ decoy aXb " + keyword.upper() + " suffix"
                self.cache.put("src_unicode", body)
                response = run_read_source(
                    ReadSourceRequest("src_unicode", keyword=keyword, limit=len(keyword)),
                    state_store=self.store,
                )
                self.assertEqual(response["match_offset"], 12)
                self.assertEqual(response["content"], keyword.upper())

    def test_unmatched_keywords_keep_existing_error_and_case_rules(self):
        for body, keyword in (
            ("İ evidence", "absent"),
            ("abc", ".*"),
            ("I", "ı"),
            ("ς", "σ"),
            ("s", "ſ"),
            ("ß", "ss"),
            ("é", "e\u0301"),
        ):
            with self.subTest(body=body, keyword=keyword):
                self.cache.put("src_unicode", body)
                with self.assertRaisesRegex(ValueError, "^keyword was not found in cached content$"):
                    run_read_source(
                        ReadSourceRequest("src_unicode", keyword=keyword),
                        state_store=self.store,
                    )

    def test_keyword_pagination_uses_original_character_offsets(self):
        body = "İ target🙂 中文 İ target end"
        self.cache.put("src_unicode", body)
        for keyword, base in (("TARGET", 2), (None, 0), ("", 0)):
            with self.subTest(keyword=keyword):
                offset = 0
                chunks = []
                for _ in range(len(body)):
                    response = run_read_source(
                        ReadSourceRequest("src_unicode", keyword=keyword, offset=offset, limit=4),
                        state_store=self.store,
                    )
                    start = base + offset
                    end = min(len(body), start + 4)
                    self.assertEqual(response["match_offset"], base if keyword else None)
                    self.assertEqual((response["start"], response["end"]), (start, end))
                    self.assertEqual(response["content"], body[start:end])
                    self.assertEqual(response["content_length"], len(body))
                    self.assertEqual(response["has_more"], end < len(body))
                    self.assertEqual(response["next_offset"], end - base if end < len(body) else None)
                    chunks.append(response["content"])
                    if not response["has_more"]:
                        break
                    offset = response["next_offset"]
                else:
                    self.fail("pagination did not terminate")
                self.assertEqual("".join(chunks), body[base:])

                exhausted = run_read_source(
                    ReadSourceRequest("src_unicode", keyword=keyword, offset=len(body) + 10),
                    state_store=self.store,
                )
                self.assertEqual((exhausted["start"], exhausted["end"]), (len(body), len(body)))
                self.assertEqual(exhausted["content"], "")
                self.assertIsNone(exhausted["next_offset"])

    def test_cache_content_hash_and_expiry_remain_unchanged(self):
        body = "İ target🙂 evidence"
        now = [datetime(2026, 9, 12, tzinfo=timezone.utc)]
        cache = ContentStore(self.store, ttl_seconds=60, clock=lambda: now[0])
        original = cache.put("src_unicode", body)
        response = run_read_source(
            ReadSourceRequest("src_unicode", keyword="TARGET", limit=6), content_store=cache,
        )
        self.assertEqual(response["content_hash"], hashlib.sha256(body.encode("utf-8")).hexdigest())
        self.assertEqual(response["expires_at"], original["expires_at"])
        self.assertEqual(cache.get("src_unicode")["content"], body)
        self.assertTrue(response["untrusted_content"])

        now[0] += timedelta(seconds=61)
        for source_id in ("src_unicode", "src_missing"):
            with self.subTest(source_id=source_id), self.assertRaisesRegex(
                ValueError, "^cached content is missing or expired; call fetch_source first$"
            ):
                run_read_source(
                    ReadSourceRequest(source_id, keyword="target"), content_store=cache,
                )

    def test_cli_and_mcp_share_unicode_results_across_pages(self):
        body = "İ [TARGET].🙂 后续"
        self.cache.put("src_unicode", body)
        with mock.patch.object(service, "StateStore", return_value=self.store):
            offset = 0
            for expected in ("[TARGET].", "🙂 后续"):
                output, errors = io.StringIO(), io.StringIO()
                result = tools.read_source_tool("src_unicode", keyword="[target].", offset=offset, limit=9)
                exit_code = cli.main(
                    ["read", "src_unicode", "--keyword", "[target].", "--offset", str(offset), "--limit", "9"],
                    stdout=output, stderr=errors,
                )
                self.assertEqual(exit_code, 0, errors.getvalue())
                self.assertEqual(result, json.loads(output.getvalue()))
                self.assertEqual(result["content"], expected)
                self.assertEqual(result["match_offset"], 2)
                offset = result["next_offset"]
            self.assertIsNone(offset)


if __name__ == "__main__":
    unittest.main()
