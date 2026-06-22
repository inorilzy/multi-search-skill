"""DeepSeek web search via direct chat.deepseek.com web API requests."""
from __future__ import annotations

import base64
import binascii
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ...support.http import urlopen_retry
from ...support.secrets import scrub_secrets


BASE_URL = "https://chat.deepseek.com"
COMPLETION_PATH = "/api/v0/chat/completion"
DEFAULT_CLIENT_VERSION = "1.5.0"
DEFAULT_APP_VERSION = "20241129.1"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0"

_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_ROT = (
    (0, 0), (1, 1), (2, 62), (3, 28), (4, 27),
    (5, 36), (6, 44), (7, 6), (8, 55), (9, 20),
    (10, 3), (11, 10), (12, 43), (13, 25), (14, 39),
    (15, 41), (16, 45), (17, 15), (18, 21), (19, 8),
    (20, 18), (21, 2), (22, 61), (23, 56), (24, 14),
)
_PI_DST = (0, 10, 20, 5, 15, 16, 1, 11, 21, 6, 7, 17, 2, 12, 22, 23, 8, 18, 3, 13, 14, 24, 9, 19, 4)


def _rotl64(value: int, bits: int) -> int:
    value &= 0xFFFFFFFFFFFFFFFF
    return ((value << bits) | (value >> (64 - bits))) & 0xFFFFFFFFFFFFFFFF if bits else value


def _keccak_f23(state: list[int]) -> None:
    for round_idx in range(1, 24):
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = (state[x + 5 * y] ^ d[x]) & 0xFFFFFFFFFFFFFFFF

        b = [0] * 25
        for src, rot in _ROT:
            b[_PI_DST[src]] = _rotl64(state[src], rot)

        for y in range(5):
            row = b[5 * y:5 * y + 5]
            for x in range(5):
                state[x + 5 * y] = (row[x] ^ ((~row[(x + 1) % 5]) & row[(x + 2) % 5])) & 0xFFFFFFFFFFFFFFFF
        state[0] ^= _RC[round_idx]


def _deepseek_hash_v1(data: bytes) -> bytes:
    rate = 136
    state = [0] * 25
    offset = 0
    while offset + rate <= len(data):
        block = data[offset:offset + rate]
        for i in range(rate // 8):
            state[i] ^= int.from_bytes(block[i * 8:i * 8 + 8], "little")
        _keccak_f23(state)
        offset += rate

    final = bytearray(rate)
    tail = data[offset:]
    final[:len(tail)] = tail
    final[len(tail)] = 0x06
    final[-1] |= 0x80
    for i in range(rate // 8):
        state[i] ^= int.from_bytes(final[i * 8:i * 8 + 8], "little")
    _keccak_f23(state)
    return b"".join(x.to_bytes(8, "little") for x in state[:4])


def _solve_pow(challenge: dict[str, Any], deadline: float | None = None) -> str:
    if challenge.get("algorithm") != "DeepSeekHashV1":
        raise ValueError(f"unsupported pow algorithm: {challenge.get('algorithm')}")
    target = binascii.unhexlify(str(challenge["challenge"]))
    prefix = f"{challenge['salt']}_{challenge['expire_at']}_".encode("utf-8")
    difficulty = int(challenge.get("difficulty") or 144000)
    answer = None
    for nonce in range(difficulty):
        if nonce & 0x3FF == 0 and deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("DeepSeek PoW timed out")
        if _deepseek_hash_v1(prefix + str(nonce).encode("ascii")) == target:
            answer = nonce
            break
    if answer is None:
        raise ValueError("DeepSeek PoW failed")
    payload = {
        "algorithm": challenge["algorithm"],
        "challenge": challenge["challenge"],
        "salt": challenge["salt"],
        "answer": answer,
        "signature": challenge["signature"],
        "target_path": challenge.get("target_path") or COMPLETION_PATH,
    }
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")


def _json_request(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen_retry(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_local_storage_token(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or value.get("token") or value.get("access_token") or "")
    text = str(value or "").strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return str(obj.get("value") or obj.get("token") or obj.get("access_token") or "")
        except json.JSONDecodeError:
            pass
    return text


def _load_auth_export(path: str | None) -> tuple[str, str]:
    if not path:
        return "", ""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    token = _extract_local_storage_token((data.get("localStorage") or {}).get("userToken"))
    cookie_parts = []
    for item in data.get("cookies") or []:
        if isinstance(item, dict) and item.get("name") and item.get("value"):
            cookie_parts.append(f"{item['name']}={item['value']}")
    return token, "; ".join(cookie_parts)


def _auth_from_config(auth: Any) -> tuple[str, str, str]:
    token = ""
    cookie = ""
    export_path = ""
    if isinstance(auth, dict):
        token = str(auth.get("token") or auth.get("access_token") or auth.get("userToken") or "")
        cookie = str(auth.get("cookie") or auth.get("cookies") or "")
        export_path = str(auth.get("auth_export") or auth.get("export_path") or "")
    elif auth:
        token = str(auth)
    return token, cookie, export_path


def _resolve_auth(auth: Any = None, token: str | None = None, cookie: str | None = None, export_path: str | None = None) -> tuple[str, str]:
    cfg_token, cfg_cookie, cfg_export = _auth_from_config(auth)
    token = token or cfg_token or os.getenv("DEEPSEEK_WEB_TOKEN") or os.getenv("DEEPSEEK_USER_TOKEN") or ""
    cookie = cookie or cfg_cookie or os.getenv("DEEPSEEK_WEB_COOKIE") or ""
    export_path = export_path or cfg_export or os.getenv("DEEPSEEK_WEB_AUTH_EXPORT") or ""
    if (not token or not cookie) and export_path:
        file_token, file_cookie = _load_auth_export(export_path)
        token = token or file_token
        cookie = cookie or file_cookie
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    return token, cookie


def _headers(token: str, cookie: str, *, accept: str = "*/*") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {token}",
        "Cookie": cookie,
        "X-App-Version": os.getenv("DEEPSEEK_WEB_APP_VERSION") or DEFAULT_APP_VERSION,
        "X-Client-Locale": os.getenv("DEEPSEEK_WEB_LOCALE") or "zh_CN",
        "X-Client-Platform": "web",
        "X-Client-Version": os.getenv("DEEPSEEK_WEB_CLIENT_VERSION") or DEFAULT_CLIENT_VERSION,
        "X-Debug-Lite-Model-Channel": "prod",
        "X-Debug-Model-Channel": "prod",
    }
    return {k: v for k, v in headers.items() if v}


def _biz_data(response: dict[str, Any], label: str) -> dict[str, Any]:
    if response.get("code") not in (0, None):
        raise ValueError(f"DeepSeek {label} failed: {response.get('msg') or response.get('message') or response.get('code')}")
    data = response.get("data") or {}
    biz = data.get("biz_data") or data
    if not isinstance(biz, dict):
        raise ValueError(f"DeepSeek {label} returned unexpected data")
    return biz


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _append_unique_result(results: list[dict[str, Any]], item: dict[str, Any]) -> None:
    url = str(item.get("url") or "").strip()
    if not url or any(row.get("url") == url for row in results):
        return
    title = item.get("title") or item.get("site_name") or item.get("host") or url
    description = item.get("snippet") or item.get("summary") or item.get("text") or item.get("content") or ""
    row = {
        "source": "deepseek-web",
        "title": str(title),
        "url": url,
        "description": str(description).strip()[:300],
    }
    if item.get("site_name"):
        row["site_name"] = item.get("site_name")
    if item.get("cite_index") is not None:
        row["cite_index"] = item.get("cite_index")
    results.append(row)


def _parse_sse(body: bytes, max_results: int) -> tuple[str, list[dict[str, Any]], str | None]:
    answer_parts: list[str] = []
    results: list[dict[str, Any]] = []
    last_path = ""
    message_id = None
    for raw_line in body.decode("utf-8", errors="replace").splitlines():
        if not raw_line.startswith("data: "):
            continue
        raw_data = raw_line[6:].strip()
        if not raw_data or raw_data == "[DONE]":
            continue
        try:
            event = json.loads(raw_data)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            last_path = str(event.get("p") or last_path)
            if "message_id" in event:
                message_id = event.get("message_id")
            v = event.get("v", event)
        else:
            v = event
        if isinstance(v, dict):
            response = v.get("response") if isinstance(v.get("response"), dict) else None
            if response:
                if response.get("message_id"):
                    message_id = response.get("message_id")
                content = response.get("content")
                if isinstance(content, str):
                    answer_parts.append(content)
            if last_path.endswith("/results") or last_path.endswith("/search/results"):
                for candidate in _walk(v):
                    if len(results) >= max_results:
                        break
                    _append_unique_result(results, candidate)
            else:
                for candidate in _walk(v):
                    if len(results) >= max_results:
                        break
                    if "url" in candidate and ("snippet" in candidate or "cite_index" in candidate or "site_name" in candidate):
                        _append_unique_result(results, candidate)
        elif isinstance(v, list):
            for candidate in _walk(v):
                if len(results) >= max_results:
                    break
                if "url" in candidate:
                    _append_unique_result(results, candidate)
        elif isinstance(v, str) and (last_path.endswith("/content") or last_path in {"response/content", "response/fragments"}):
            answer_parts.append(v)
    answer = "".join(answer_parts).strip()
    return answer, results[:max_results], str(message_id) if message_id else None


def search_deepseek_web(
    query: str,
    max_results: int = 10,
    auth: Any = None,
    timeout: float = 120,
    token: str | None = None,
    cookie: str | None = None,
    export_path: str | None = None,
) -> list[dict[str, Any]]:
    """Call DeepSeek's web chat API with native search_enabled=true."""
    token, cookie = _resolve_auth(auth=auth, token=token, cookie=cookie, export_path=export_path)
    secrets = [token, cookie, export_path]
    if not token:
        return [{"source": "deepseek-web", "error": "skipped: missing DEEPSEEK_WEB_TOKEN or DEEPSEEK_WEB_AUTH_EXPORT"}]
    if not cookie:
        return [{"source": "deepseek-web", "error": "skipped: missing DEEPSEEK_WEB_COOKIE or DEEPSEEK_WEB_AUTH_EXPORT"}]

    try:
        deadline = time.monotonic() + max(float(timeout), 0.1)

        def remaining(default: float = 30.0) -> float:
            return max(0.1, min(default, deadline - time.monotonic()))

        base_headers = _headers(token, cookie)
        session_resp = _json_request(f"{BASE_URL}/api/v0/chat_session/create", {}, base_headers, remaining(30))
        chat_session_id = _biz_data(session_resp, "session create").get("id")
        if not chat_session_id:
            raise ValueError("DeepSeek session create did not return id")

        pow_resp = _json_request(
            f"{BASE_URL}/api/v0/chat/create_pow_challenge",
            {"target_path": COMPLETION_PATH, "scene": "completion_like"},
            base_headers,
            remaining(30),
        )
        challenge = _biz_data(pow_resp, "pow challenge").get("challenge")
        if not isinstance(challenge, dict):
            raise ValueError("DeepSeek pow challenge missing")
        pow_header = _solve_pow(challenge, deadline=deadline)

        prompt = f"{query}\n\n请使用联网搜索，返回可靠网页来源。"
        completion_payload = {
            "chat_session_id": chat_session_id,
            "parent_message_id": None,
            "model_type": os.getenv("DEEPSEEK_WEB_MODEL") or "default",
            "prompt": prompt,
            "ref_file_ids": [],
            "thinking_enabled": False,
            "search_enabled": True,
            "user_options": {},
        }
        completion_headers = _headers(token, cookie, accept="text/event-stream")
        completion_headers["X-DS-PoW-Response"] = pow_header
        req = urllib.request.Request(
            f"{BASE_URL}{COMPLETION_PATH}",
            data=json.dumps(completion_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers=completion_headers,
            method="POST",
        )
        with urlopen_retry(req, timeout=remaining(float(timeout))) as resp:
            content_type = resp.headers.get("content-type", "")
            body = resp.read()
        if "text/event-stream" not in content_type.lower():
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                data = {"raw": body.decode("utf-8", errors="replace")[:300]}
            biz = _biz_data(data, "completion")
            detail = biz.get("biz_msg") or data.get("msg") or data.get("message") or data.get("raw") or "non-SSE response"
            if biz.get("is_muted"):
                detail = f"user is muted until {biz.get('mute_until')}"
            return [{"source": "deepseek-web", "error": scrub_secrets(f"DeepSeek completion returned JSON: {detail}", secrets)}]
        answer, citations, _ = _parse_sse(body, max_results=max_results)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        return [{"source": "deepseek-web", "error": scrub_secrets(f"HTTP {e.code}: {detail}", secrets)}]
    except Exception as e:
        return [{"source": "deepseek-web", "error": scrub_secrets(e, secrets)}]

    rows: list[dict[str, Any]] = []
    if answer:
        rows.append({"source": "deepseek_web_answer", "answer": answer})
    rows.extend(citations)
    if not rows:
        rows.append({"source": "deepseek-web", "status": "ok", "raw_hits": 0})
    return rows
