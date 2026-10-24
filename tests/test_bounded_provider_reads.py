"""Provider response bodies, error bodies and decompressed bodies are size-bounded."""
import gzip
import io
import json
import unittest
import urllib.error
import zlib
from email.message import Message
from unittest import mock

from multi_search_mcp.src.support import http
from multi_search_mcp.src.support.http import (
    ERROR_BODY_LIMIT,
    MAX_RESPONSE_BYTES,
    ResponseTooLargeError,
    decompress_limited,
    read_error_body,
    read_limited,
)
from multi_search_mcp.src.state.key_state import classify_error


class FakeResponse:
    """Response honouring read(size) the way HTTPResponse does; records sizes."""

    def __init__(self, body: bytes, headers=None):
        self.stream = io.BytesIO(body)
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.stream.read(size)

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _gzip_bomb(decompressed_bytes: int) -> bytes:
    # Highly compressible: ~10 KiB of gzip per 10 MiB of zeros.
    return gzip.compress(b"\0" * decompressed_bytes)


class ReadLimitedTests(unittest.TestCase):
    def test_body_within_the_limit_is_returned_whole(self):
        resp = FakeResponse(b'{"ok": true}')
        self.assertEqual(read_limited(resp), b'{"ok": true}')
        self.assertEqual(resp.read_sizes, [MAX_RESPONSE_BYTES + 1])

    def test_body_exactly_at_the_limit_is_accepted(self):
        self.assertEqual(read_limited(FakeResponse(b"x" * 16), max_bytes=16), b"x" * 16)

    def test_oversize_body_is_rejected_without_reading_past_limit_plus_one(self):
        resp = FakeResponse(b"x" * 1000)
        with self.assertRaises(ResponseTooLargeError):
            read_limited(resp, max_bytes=100)
        self.assertEqual(resp.read_sizes, [101])
        # Only limit+1 bytes were consumed from the stream.
        self.assertEqual(resp.stream.tell(), 101)

    def test_declared_oversize_content_length_is_rejected_before_reading(self):
        resp = FakeResponse(b"{}", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)})
        with self.assertRaises(ResponseTooLargeError):
            read_limited(resp)
        self.assertEqual(resp.read_sizes, [])

    def test_unparsable_content_length_falls_back_to_the_read_bound(self):
        resp = FakeResponse(b"{}", headers={"Content-Length": "not-a-number"})
        self.assertEqual(read_limited(resp), b"{}")

    def test_size_error_is_not_retried_and_does_not_cool_a_key(self):
        error = ResponseTooLargeError("provider response body", MAX_RESPONSE_BYTES)
        self.assertNotIsInstance(error, OSError)
        self.assertEqual(classify_error(str(error)), "error")


class DecompressLimitedTests(unittest.TestCase):
    def test_gzip_within_the_limit_round_trips(self):
        payload = json.dumps({"items": list(range(100))}).encode()
        self.assertEqual(decompress_limited(gzip.compress(payload), "gzip"), payload)

    def test_deflate_zlib_and_raw_round_trip(self):
        payload = b'{"items": []}'
        raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        raw_deflate = raw.compress(payload) + raw.flush()
        self.assertEqual(decompress_limited(zlib.compress(payload), "deflate"), payload)
        self.assertEqual(decompress_limited(raw_deflate, "deflate"), payload)

    def test_gzip_bomb_is_rejected_by_decompressed_size(self):
        bomb = _gzip_bomb(MAX_RESPONSE_BYTES * 2)
        self.assertLess(len(bomb), MAX_RESPONSE_BYTES)  # passes the raw read bound
        with self.assertRaises(ResponseTooLargeError):
            decompress_limited(bomb, "gzip")

    def test_deflate_bomb_is_rejected_by_decompressed_size(self):
        bomb = zlib.compress(b"\0" * 4096)
        with self.assertRaises(ResponseTooLargeError):
            decompress_limited(bomb, "deflate", max_bytes=1024)

    def test_truncated_gzip_is_an_invalid_response_not_a_success(self):
        truncated = gzip.compress(b"x" * 1000)[:-12]
        with self.assertRaisesRegex(ValueError, "invalid gzip"):
            decompress_limited(truncated, "gzip")

    def test_unknown_encoding_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported Content-Encoding"):
            decompress_limited(b"", "br")


class ErrorBodyTests(unittest.TestCase):
    def test_error_body_read_is_bounded(self):
        fp = FakeResponse(b"e" * (ERROR_BODY_LIMIT * 10))
        exc = urllib.error.HTTPError("https://r.jina.ai/x", 500, "boom", Message(), fp)
        body = read_error_body(exc)
        self.assertEqual(len(body), ERROR_BODY_LIMIT)
        self.assertEqual(fp.read_sizes, [ERROR_BODY_LIMIT])

    def test_jina_error_message_reads_a_bounded_body(self):
        from multi_search_mcp.src.scrape.scrapers import jina

        fp = FakeResponse(b"x" * (ERROR_BODY_LIMIT * 10))
        exc = urllib.error.HTTPError("https://r.jina.ai/x", 500, "boom", Message(), fp)
        message = jina._jina_error_message(exc)
        self.assertEqual(len(message), ERROR_BODY_LIMIT)
        self.assertEqual(fp.read_sizes, [ERROR_BODY_LIMIT])


class ProviderIntegrationTests(unittest.TestCase):
    """Each provider turns an oversize body into a provider error row."""

    def setUp(self):
        # Stop only these patchers: mock.patch.stopall() would also stop the
        # suite's network-isolation guard patches for every later test.
        for patcher in (
            mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")),
            mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected network")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _patch_urlopen(self, module, response):
        return mock.patch.object(module, "urlopen_retry", return_value=response)

    def test_brave_rejects_a_gzip_bomb(self):
        from multi_search_mcp.src.search.searchers import brave

        resp = FakeResponse(_gzip_bomb(MAX_RESPONSE_BYTES * 2), headers={"Content-Encoding": "gzip"})
        with self._patch_urlopen(brave, resp):
            rows = brave.search_brave("q", "synthetic-brave-key")
        self.assertEqual(len(rows), 1)
        self.assertIn("size cap", rows[0]["error"])

    def test_brave_rejects_an_oversize_raw_body(self):
        from multi_search_mcp.src.search.searchers import brave

        resp = FakeResponse(b"{" + b" " * MAX_RESPONSE_BYTES + b"}")
        with self._patch_urlopen(brave, resp):
            rows = brave.search_brave("q", "synthetic-brave-key")
        self.assertIn("size cap", rows[0]["error"])
        self.assertEqual(resp.read_sizes, [MAX_RESPONSE_BYTES + 1])

    def test_stackoverflow_rejects_a_gzip_bomb(self):
        from multi_search_mcp.src.search.searchers import stackoverflow

        resp = FakeResponse(_gzip_bomb(MAX_RESPONSE_BYTES * 2), headers={"Content-Encoding": "gzip"})
        with self._patch_urlopen(stackoverflow, resp):
            rows = stackoverflow.search_stackoverflow("q")
        self.assertEqual(len(rows), 1)
        self.assertIn("size cap", rows[0]["error"])

    def test_json_searchers_reject_oversize_bodies(self):
        from multi_search_mcp.src.search.searchers import exa, hackernews, parallel, tavily

        calls = (
            (hackernews, lambda: hackernews.search_hackernews("q")),
            (exa, lambda: exa.search_exa("q", "synthetic-exa-key")),
            (parallel, lambda: parallel.search_parallel("q", "synthetic-parallel-key")),
            (tavily, lambda: tavily.search_tavily("q", "synthetic-tavily-key")),
        )
        for module, call in calls:
            with self.subTest(provider=module.__name__):
                resp = FakeResponse(b"[" + b" " * MAX_RESPONSE_BYTES + b"]")
                with self._patch_urlopen(module, resp):
                    rows = call()
                self.assertTrue(rows and rows[0].get("error"), rows)
                self.assertIn("size cap", rows[0]["error"])
                self.assertEqual(resp.read_sizes, [MAX_RESPONSE_BYTES + 1])

    def test_jina_scraper_rejects_an_oversize_body(self):
        from multi_search_mcp.src.scrape.scrapers import jina

        resp = FakeResponse(b"{" + b" " * MAX_RESPONSE_BYTES + b"}")
        with self._patch_urlopen(jina, resp):
            result = jina.scrape_url_jina("https://example.com/page", skip_anonymous=False)
        self.assertIn("error", result)
        self.assertEqual(resp.read_sizes, [MAX_RESPONSE_BYTES + 1])


class CallSiteContractTests(unittest.TestCase):
    """No provider module may read a response body without a bound."""

    def test_no_unbounded_response_reads_remain(self):
        import pathlib
        import re

        root = pathlib.Path(http.__file__).resolve().parents[1]
        offenders = []
        pattern = re.compile(r"\b(resp|response|exc|e)\.read\(\s*\)|gzip\.decompress\(|zlib\.decompress\(")
        for path in list((root / "search" / "searchers").glob("*.py")) + list(
            (root / "scrape" / "scrapers").glob("*.py")
        ):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
