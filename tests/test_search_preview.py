import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.state_store import StateStore


TITLE = "TaskGroup cancellation"
URL = "https://example.com/taskgroup"


class SearchPreviewTests(unittest.TestCase):
    def search(self, body, *, limit=1200, store=None, snippet="candidate excerpt"):
        provider = ProviderSpec(
            name="brave", public_name="brave",
            call=lambda *_: [{
                "source": "brave", "title": TITLE, "url": URL,
                "description": snippet, "content_kind": "excerpt",
            }],
        )
        return service.run_search_web(
            service.SearchWebRequest(
                query="TaskGroup", sources=["brave"], count=1,
                use_state=store is not None,
            ),
            providers={"brave": provider}, keys={}, config={}, state_store=store,
            scrape_chars=limit,
            scraper=lambda url, **_: {"url": url, "markdown": body, "via": "fixture"},
            url_resolver=lambda _: ["93.184.216.34"],
        )

    def test_navigation_no_longer_hides_question_and_full_body_is_unchanged(self):
        heading = f"# [{TITLE}]({URL})\n\n"
        prefix = "##### Community\n\n" + "Browse products and teams.\n\n" * 30
        question = "I need to understand why sibling tasks are cancelled.\n\n"
        body = prefix + heading + "Asked yesterday.\n\n" * 24 + question * 40
        self.assertNotIn(question, body[:1200])
        with TemporaryDirectory() as temp:
            store = StateStore(Path(temp) / "state.sqlite")
            for _ in range(2):
                response = self.search(body, store=store)
                page = response["scrapes"][0]
                self.assertIn(question, page["markdown"])
                self.assertEqual(page["preview_start"], len(prefix))
                self.assertEqual(page["preview_end"], len(prefix) + 1200)
                self.assertEqual(page["markdown"], body[page["preview_start"]:page["preview_end"]])
                self.assertEqual(page["length"], len(body))
                self.assertTrue(page["truncated"])
                fetched = service.run_fetch_source(
                    service.FetchSourceRequest(source_id=page["source_id"], full_content=True),
                    state_store=store, url_resolver=lambda _: ["93.184.216.34"],
                )
                self.assertTrue(fetched["cache_hit"])
                self.assertEqual(fetched["body"], body)
                self.assertFalse(fetched["truncated"])
                read = service.run_read_source(service.ReadSourceRequest(
                    source_id=page["source_id"], offset=page["preview_start"], limit=1200,
                ), state_store=store)
                self.assertEqual(read["content"], page["markdown"])
                self.assertEqual(read["content_hash"], fetched["content_hash"])

    def test_only_an_exact_top_level_title_anchors_the_preview(self):
        for heading in (f"# {TITLE}\n", f"{TITLE}\n======\n", f"# [{TITLE}]({URL})\n"):
            with self.subTest(heading=heading):
                prefix = "[Home](https://example.com)\n\n"
                body = prefix + heading + "\nQuestion."
                page = self.search(body, limit=len(body) - 1)["scrapes"][0]
                self.assertEqual(page["markdown"], body[len(prefix):])
                self.assertEqual(page["preview_start"], len(prefix))
                self.assertEqual(page["preview_end"], len(body))
                # Omitting the prefix still counts as truncation.
                self.assertTrue(page["truncated"])

    def test_body_that_fits_the_budget_keeps_its_entire_prefix(self):
        body = f"Intro\n\n# {TITLE}\n\nQuestion."
        page = self.search(body)["scrapes"][0]
        self.assertEqual(page["markdown"], body)
        self.assertEqual(page["preview_start"], 0)
        self.assertFalse(page["truncated"])

    def test_exact_excerpt_locates_body_without_a_title_and_keeps_original_whitespace(self):
        prefix = "Community navigation.\n\n" * 70
        paragraph = "I want to learn Python systematically.\n\nI have used Python for some time."
        body = prefix + paragraph + " More details." * 100
        snippet = "I want to learn Python systematically. I have used Python for some time."
        page = self.search(body, snippet=snippet)["scrapes"][0]
        self.assertEqual(page["preview_start"], len(prefix))
        self.assertTrue(page["markdown"].startswith(paragraph))
        self.assertEqual(page["markdown"], body[len(prefix):len(prefix) + 1200])

    def test_short_paraphrased_or_mid_paragraph_snippets_do_not_move_the_preview(self):
        for snippet in ("Python", "A paraphrase that never appears in the original body text.",
                        "Python systematically and understand task cancellation behavior."):
            body = "Site navigation.\n\nI want to learn Python systematically and understand task cancellation behavior."
            with self.subTest(snippet=snippet):
                page = self.search(body, limit=30, snippet=snippet)["scrapes"][0]
                self.assertEqual(page["preview_start"], 0)
                self.assertEqual(page["markdown"], body[:30])

    def test_unmatched_titles_and_code_examples_keep_the_original_prefix(self):
        for body in (
            "An ordinary body without headings.",
            f"Intro\n\n## {TITLE}\n\nSection content.",
            f"Intro\n\n# {TITLE} and more\n\nDifferent article.",
            f"```markdown\n# {TITLE}\n```\n\nA code example.",
            f"~~~markdown\n{TITLE}\n===\n~~~\n\nA code example.",
            f"Opening context is part of the heading\n{TITLE}\n======\n\nQuestion.",
            f"Intro\n\n \t{TITLE}\n======\n\nA code example.",
        ):
            with self.subTest(body=body):
                page = self.search(body, limit=30)["scrapes"][0]
                self.assertEqual(page["markdown"], body[:30])
                self.assertEqual(page["preview_start"], 0)
                self.assertEqual(page["preview_end"], min(30, len(body)))
                self.assertEqual(page["truncated"], len(body) > 30)


if __name__ == "__main__":
    unittest.main()
