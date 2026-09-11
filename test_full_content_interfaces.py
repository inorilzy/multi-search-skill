import asyncio
import io
import json
import unittest
from contextlib import ExitStack
from unittest import mock

from multi_search_mcp import cli, tools
from multi_search_mcp.server import mcp
from multi_search_mcp.src import service


URL = "https://evidence.example/full-content"
MARKER = "UNIQUE_FULL_CONTENT_BODY"
BODY = MARKER + " acquired source text" * 1500


class FullContentInterfaceTests(unittest.TestCase):
    def setUp(self):
        # Windows creates a local socket pair while initializing an event loop.
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(
            service, "load_keys", side_effect=AssertionError("unexpected key loading"),
        ))
        stack.enter_context(mock.patch.object(
            service, "load_config", side_effect=AssertionError("unexpected config loading"),
        ))
        stack.enter_context(mock.patch(
            "socket.getaddrinfo", side_effect=AssertionError("unexpected DNS"),
        ))
        stack.enter_context(mock.patch(
            "socket.socket.connect", side_effect=AssertionError("unexpected connection"),
        ))

    def test_cli_full_content_flag_and_legacy_defaults_reach_the_service(self):
        cases = (
            ([], False, 20_000),
            (["--max-chars", "1200"], False, 1200),
            (["--full-content"], True, 20_000),
            (["--full-content", "--max-chars", "1200"], True, 1200),
        )
        for options, full_content, max_chars in cases:
            with self.subTest(options=options):
                stdout, stderr = io.StringIO(), io.StringIO()
                expected = {"source_id": "source_1", "body": "fixture body"}
                with mock.patch.object(cli, "run_fetch_source", return_value=expected) as run:
                    code = cli.main(
                        ["fetch", "source_1", *options], stdout=stdout, stderr=stderr,
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertEqual(json.loads(stdout.getvalue()), expected)
                request = run.call_args.args[0]
                self.assertEqual(request.source_id, "source_1")
                self.assertIs(request.full_content, full_content)
                self.assertEqual(request.max_chars, max_chars)

    def test_cli_formats_preserve_the_complete_body_once(self):
        for output_format in ("json", "human", "markdown"):
            with self.subTest(output_format=output_format):
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(cli, "run_fetch_source", return_value={"body": BODY}):
                    code = cli.main([
                        "fetch", "--url", URL, "--full-content", "--max-chars", "1200",
                        "--format", output_format,
                    ], stdout=stdout, stderr=stderr)
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn(BODY, stdout.getvalue())
                self.assertEqual(stdout.getvalue().count(MARKER), 1)

    def test_fetch_tool_preserves_positional_arguments_and_false_default(self):
        cases = (
            (("source_1", None, ["jina"], 1200, 5, False), False),
            (("source_1", None, ["jina"], 1200, 5, False, False), False),
            (("source_1", None, ["jina"], 1200, 5, False, True), True),
        )
        for arguments, full_content in cases:
            with self.subTest(arguments=arguments):
                expected = {"body": "fixture body"}
                with mock.patch.object(tools, "run_fetch_source", return_value=expected) as run:
                    result = tools.fetch_source_tool(*arguments)
                self.assertEqual(result, expected)
                request = run.call_args.args[0]
                self.assertEqual(request.source_id, "source_1")
                self.assertEqual(request.backends, ["jina"])
                self.assertEqual(request.max_chars, 1200)
                self.assertEqual(request.timeout, 5)
                self.assertIs(request.use_state, False)
                self.assertIs(request.full_content, full_content)

    def test_registered_mcp_schema_exposes_optional_full_content(self):
        registered = {tool.name: tool for tool in self.loop.run_until_complete(mcp.list_tools())}
        schema = registered["fetch_source"].inputSchema
        self.assertEqual(schema["properties"]["full_content"]["type"], "boolean")
        self.assertIs(schema["properties"]["full_content"]["default"], False)
        self.assertNotIn("full_content", schema.get("required", []))
        self.assertEqual(schema["properties"]["max_chars"]["default"], 20_000)

    def test_search_tool_descriptions_do_not_impose_a_source_quota(self):
        registered = {tool.name: tool for tool in self.loop.run_until_complete(mcp.list_tools())}
        for name in ("search_web", "multi_search"):
            with self.subTest(tool=name):
                description = " ".join(registered[name].description.split())
                self.assertNotIn("3-5", description)
                self.assertIn("only clearly irrelevant candidates", description)
                self.assertIn("relevant or uncertain candidate without a fixed quota", description)
                self.assertIn("Find-only requests can return matching links", description)
                self.assertIn("fetch selected full bodies", description)

    def test_registered_mcp_call_preserves_limits_unless_full_content_is_true(self):
        def fetch_fixture(request):
            return service.run_fetch_source(
                request, keys={}, config={}, prefetched_body=BODY,
                url_resolver=lambda _host: ["93.184.216.34"],
            )

        cases = (
            ({}, 20_000),
            ({"full_content": False, "max_chars": 1200}, 1200),
            ({"full_content": True, "max_chars": 1200}, len(BODY)),
        )
        for options, expected_length in cases:
            with self.subTest(options=options):
                with mock.patch.object(tools, "run_fetch_source", side_effect=fetch_fixture):
                    response = self.loop.run_until_complete(mcp.call_tool(
                        "fetch_source", {"url": URL, "use_state": False, **options},
                    ))
                texts = [item.text for item in response if getattr(item, "type", None) == "text"]
                self.assertEqual(len(texts), 1)
                self.assertEqual(texts[0].count(MARKER), 1)
                payload = json.loads(texts[0])
                self.assertEqual(payload["body"], BODY[:expected_length])
                self.assertEqual(payload["content_length"], len(BODY))
                self.assertIs(payload["truncated"], expected_length < len(BODY))


if __name__ == "__main__":
    unittest.main()
