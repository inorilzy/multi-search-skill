import json
import unittest
from unittest import mock

from multi_search_mcp.src.scrape.scrapers import jina


URL = "https://www.php.cn/faq/2306825.html"
CHALLENGE = (
    "# www.php.cn\n\n## Performing security verification\n\n"
    "This website uses a security service to protect against malicious bots. "
    "This page is displayed while the website verifies you are not a bot.\n\n"
    "## Verification successful. Waiting for www.php.cn to respond"
)


class _Response:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"data": self.page}).encode("utf-8")


class JinaBlockedContentTests(unittest.TestCase):
    def scrape(self, *, title, content):
        with mock.patch.object(jina, "urlopen_retry", return_value=_Response({
            "title": title, "content": content,
        })) as request:
            result = jina.scrape_url_jina(URL, api_key="fixture-key")
        request.assert_called_once()
        return result

    def test_observed_security_challenge_is_an_error_without_body(self):
        result = self.scrape(title="Just a moment...", content=CHALLENGE)
        self.assertIn("blocked", result.get("error", ""))
        self.assertNotIn("markdown", result)
        self.assertNotIn("length", result)
        self.assertNotIn("rate_limited", result)
        self.assertNotIn("exhausted", result)

    def test_article_quoting_verification_page_is_not_blocked(self):
        result = self.scrape(title="How to diagnose a website security challenge", content=CHALLENGE)
        self.assertNotIn("error", result)
        self.assertEqual(result["markdown"], CHALLENGE)

    def test_similar_title_without_challenge_body_is_not_blocked(self):
        result = self.scrape(title="Just a moment...", content="# An ordinary article\nContent.")
        self.assertNotIn("error", result)
        self.assertEqual(result["markdown"], "# An ordinary article\nContent.")

    def test_heading_alone_does_not_classify_body_as_a_challenge(self):
        content = "## Performing security verification\n\nA tutorial describing test automation."
        result = self.scrape(title="Just a moment...", content=content)
        self.assertNotIn("error", result)
        self.assertEqual(result["markdown"], content)


if __name__ == "__main__":
    unittest.main()
