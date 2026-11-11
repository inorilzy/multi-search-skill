import unittest

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec

TITLE = "TaskGroup cancellation"
URL = "https://example.com/taskgroup"
PREFIX = "##### Community\n\n" + "Browse products and teams.\n\n" * 30
PARAGRAPH = (
    "TaskGroup cancellation is triggered when a child task fails and the "
    "runtime cancels every sibling immediately."
)
FILLER = "More background details follow. " * 100


class PreviewAnchoringTests(unittest.TestCase):
    def search(self, body, *, limit=1200, snippet=""):
        provider = ProviderSpec(
            name="brave", public_name="brave",
            call=lambda *_: [{
                "source": "brave", "title": TITLE, "url": URL,
                "description": snippet, "content_kind": "excerpt",
            }],
        )
        return service.run_search_web(
            service.SearchWebRequest(
                query="TaskGroup", sources=["brave"], count=1, use_state=False,
            ),
            providers={"brave": provider}, keys={}, config={}, state_store=None,
            scrape_chars=limit,
            scraper=lambda url, **_: {"url": url, "markdown": body, "via": "fixture"},
        )

    def assert_anchors_paragraph(self, snippet):
        body = PREFIX + PARAGRAPH + "\n\n" + FILLER
        page = self.search(body, snippet=snippet)["scrapes"][0]
        self.assertEqual(page["preview_start"], len(PREFIX))
        self.assertTrue(page["markdown"].startswith(PARAGRAPH))
        self.assertTrue(page["truncated"])

    def test_unicode_ellipsis_snippet_anchors_its_paragraph(self):
        self.assert_anchors_paragraph(PARAGRAPH[:70] + "…")

    def test_ascii_ellipsis_snippet_anchors_its_paragraph(self):
        self.assert_anchors_paragraph(PARAGRAPH[:70] + "...")

    def test_hard_truncated_snippet_anchors_its_paragraph(self):
        # The provider cut lands in the middle of "sibling".
        self.assert_anchors_paragraph(PARAGRAPH[: PARAGRAPH.index("sibling") + 3])

    def test_middot_joined_snippet_anchors_its_matching_part(self):
        # Brave joins a description with extra snippets using " · ".
        snippet = PARAGRAPH[:70] + " · Another fragment from a different part of the page."
        self.assert_anchors_paragraph(snippet)

    def test_same_line_closed_backtick_fence_does_not_hide_following_h1(self):
        inline_code = "```python print('x')```\n\n"
        body = PREFIX + inline_code + f"# {TITLE}\n\n" + FILLER
        page = self.search(body)["scrapes"][0]
        self.assertEqual(page["preview_start"], len(PREFIX) + len(inline_code))
        self.assertTrue(page["markdown"].startswith(f"# {TITLE}"))

    def test_snippet_with_31_non_whitespace_characters_does_not_move_the_preview(self):
        paragraph = "TaskGroup cancellation happens now"
        body = PREFIX + paragraph + "\n\n" + FILLER
        page = self.search(body, snippet=paragraph)["scrapes"][0]
        self.assertEqual(page["preview_start"], 0)

    def test_short_snippet_with_ellipsis_does_not_move_the_preview(self):
        paragraph = "TaskGroup cancellation happens now"
        body = PREFIX + paragraph + "\n\n" + FILLER
        page = self.search(body, snippet=paragraph + "…")["scrapes"][0]
        self.assertEqual(page["preview_start"], 0)

    def test_snippet_with_32_non_whitespace_characters_anchors_its_paragraph(self):
        paragraph = "TaskGroup cancellation happens now."
        body = PREFIX + paragraph + "\n\n" + FILLER
        page = self.search(body, snippet=paragraph)["scrapes"][0]
        self.assertEqual(page["preview_start"], len(PREFIX))


if __name__ == "__main__":
    unittest.main()
