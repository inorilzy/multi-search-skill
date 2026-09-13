import io
import json
import unittest
from unittest import mock

from multi_search_mcp import cli


class CLIEncodingTests(unittest.TestCase):
    def test_windows_redirected_output_uses_utf8_in_every_format(self):
        payload = {"source_id": "src_unicode", "body": "中文 ⌨ ™ ›"}
        for output_format in cli.OUTPUT_FORMATS:
            with self.subTest(output_format=output_format):
                buffer = io.BytesIO()
                stdout = io.TextIOWrapper(buffer, encoding="gbk")
                stderr = io.StringIO()
                with mock.patch.object(cli.sys, "platform", "win32"), \
                     mock.patch.object(cli.sys, "stdout", stdout), \
                     mock.patch.object(cli.sys, "stderr", stderr), \
                     mock.patch.object(cli.sys, "argv", ["multi-search", "fetch", "src_unicode", "--format", output_format]), \
                     mock.patch.object(cli, "run_fetch_source", return_value=payload), \
                     self.assertRaises(SystemExit) as raised:
                    cli.entrypoint()
                stdout.flush()
                self.assertEqual(raised.exception.code, 0, stderr.getvalue())
                rendered = buffer.getvalue().decode("utf-8")
                self.assertIn(payload["body"], rendered)
                if output_format == "json":
                    self.assertEqual(json.loads(rendered), payload)

    def test_windows_redirected_error_keeps_unicode_and_failure_exit(self):
        buffer = io.BytesIO()
        stderr = io.TextIOWrapper(buffer, encoding="gbk", errors="backslashreplace", newline="\n")
        with mock.patch.object(cli.sys, "platform", "win32"), \
             mock.patch.object(cli.sys, "stdout", io.StringIO()), \
             mock.patch.object(cli.sys, "stderr", stderr), \
             mock.patch.object(cli.sys, "argv", ["multi-search", "fetch", "src_unicode"]), \
             mock.patch.object(cli, "run_fetch_source", side_effect=ValueError("正文失败 ⌨")), \
             self.assertRaises(SystemExit) as raised:
            cli.entrypoint()
        stderr.flush()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(stderr.errors, "backslashreplace")
        self.assertEqual(buffer.getvalue().decode("utf-8"), "error: 正文失败 ⌨\n")

    def test_windows_console_encoding_is_unchanged(self):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
        stderr = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
        with mock.patch.object(stdout, "isatty", return_value=True), \
             mock.patch.object(stderr, "isatty", return_value=True), \
             mock.patch.object(cli.sys, "platform", "win32"), \
             mock.patch.object(cli.sys, "stdout", stdout), \
             mock.patch.object(cli.sys, "stderr", stderr), \
             mock.patch.object(cli, "main", return_value=0), \
             self.assertRaises(SystemExit) as raised:
            cli.entrypoint()
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.encoding, "gbk")
        self.assertEqual(stderr.encoding, "gbk")

    def test_custom_streams_remain_supported(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli.sys, "platform", "win32"), \
             mock.patch.object(cli.sys, "stdout", stdout), \
             mock.patch.object(cli.sys, "stderr", stderr), \
             mock.patch.object(cli, "main", return_value=0), \
             self.assertRaises(SystemExit) as raised:
            cli.entrypoint()
        self.assertEqual(raised.exception.code, 0)

    def test_non_windows_redirected_encoding_is_unchanged(self):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="latin-1")
        with mock.patch.object(cli.sys, "platform", "linux"), \
             mock.patch.object(cli.sys, "stdout", stdout), \
             mock.patch.object(cli, "main", return_value=0), \
             self.assertRaises(SystemExit) as raised:
            cli.entrypoint()
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.encoding, "latin-1")


if __name__ == "__main__":
    unittest.main()
