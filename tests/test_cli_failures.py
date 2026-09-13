import io
import json
import unittest
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec


class SearchFailureTests(unittest.TestCase):
    def run_search(self, providers, *, expand=None, output_format="json"):
        def run(request):
            request.use_state = False
            return service.run_search_web(request, providers=providers, keys={}, config={})

        stdout, stderr = io.StringIO(), io.StringIO()
        args = ["search", "probe", "--format", output_format]
        for source in providers:
            args.extend(["--source", source])
        for query in expand or []:
            args.extend(["--expand", query])
        with mock.patch.object(cli, "run_search_web", side_effect=run):
            code = cli.main(args, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_all_failed_is_visible_and_nonzero_in_every_format(self):
        providers = {"brave": ProviderSpec(
            name="brave", public_name="brave",
            call=lambda *_: [{"source": "brave", "error": "missing API key"}],
        )}
        for output_format in cli.OUTPUT_FORMATS:
            with self.subTest(output_format=output_format):
                code, stdout, stderr = self.run_search(providers, output_format=output_format)
                self.assertEqual(code, 1)
                self.assertIn("missing API key", stdout)
                self.assertIn("all selected search providers failed", stderr)
                if output_format == "json":
                    self.assertEqual(json.loads(stdout)["results"], [])

    def test_successful_empty_search_exits_zero(self):
        providers = {"brave": ProviderSpec(name="brave", public_name="brave", call=lambda *_: [])}
        for output_format in cli.OUTPUT_FORMATS:
            with self.subTest(output_format=output_format):
                code, _stdout, stderr = self.run_search(providers, output_format=output_format)
                self.assertEqual(code, 0, stderr)

    def test_empty_success_and_failed_provider_are_partial_coverage(self):
        providers = {
            "brave": ProviderSpec(name="brave", public_name="brave", call=lambda *_: []),
            "exa": ProviderSpec(name="exa", public_name="exa", call=lambda *_: [{"source": "exa", "error": "quota exceeded"}]),
        }
        for output_format in cli.OUTPUT_FORMATS:
            with self.subTest(output_format=output_format):
                code, stdout, stderr = self.run_search(providers, output_format=output_format)
                self.assertEqual(code, 0, stderr)
                self.assertIn("quota exceeded", stdout)

    def test_one_successful_empty_query_prevents_all_failed_status(self):
        providers = {"brave": ProviderSpec(
            name="brave", public_name="brave",
            call=lambda query, *_: [] if query == "probe" else [{"source": "brave", "error": "timeout"}],
        )}
        code, stdout, stderr = self.run_search(providers, expand=["variant"])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["provider_status"][0]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
