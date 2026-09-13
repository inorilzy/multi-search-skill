import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class HostOpenerIsolationTests(unittest.TestCase):
    def _run_probe(self, source):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent)
        result = subprocess.run(
            [sys.executable, "-B", "-c", textwrap.dedent(source)],
            cwd=Path(__file__).resolve().parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"probe failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result.stdout

    def test_import_preserves_existing_host_opener_after_private_request(self):
        output = self._run_probe(
            """
            import email.message
            import io
            import urllib.request
            import urllib.response

            class MemoryHandler(urllib.request.BaseHandler):
                def __init__(self, body):
                    self.body = body

                def memory_open(self, request):
                    headers = email.message.Message()
                    return urllib.response.addinfourl(
                        io.BytesIO(self.body), headers, request.full_url, 200,
                    )

            host_opener = urllib.request.build_opener(MemoryHandler(b"host-response"))
            urllib.request.install_opener(host_opener)
            assert urllib.request.urlopen("memory://probe").read() == b"host-response"

            from multi_search_mcp.src.support import http

            assert urllib.request._opener is host_opener
            with http.urlopen_retry(
                "memory://probe",
                timeout=1,
                extra_handlers=(MemoryHandler(b"private-response"),),
            ) as response:
                assert response.read() == b"private-response"
            assert urllib.request._opener is host_opener
            assert urllib.request.urlopen("memory://probe").read() == b"host-response"
            assert "multi_search_mcp" in str(http.__file__)
            print("existing-host-opener-ok")
            """
        )
        self.assertIn("existing-host-opener-ok", output)

    def test_import_and_private_request_do_not_initialize_host_opener(self):
        output = self._run_probe(
            """
            import email.message
            import io
            import urllib.request
            import urllib.response

            assert urllib.request._opener is None

            class MemoryHandler(urllib.request.BaseHandler):
                def memory_open(self, request):
                    headers = email.message.Message()
                    return urllib.response.addinfourl(
                        io.BytesIO(b"private-response"), headers, request.full_url, 200,
                    )

            from multi_search_mcp.src.support import http

            assert urllib.request._opener is None
            with http.urlopen_retry(
                "memory://probe",
                timeout=1,
                extra_handlers=(MemoryHandler(),),
            ) as response:
                assert response.read() == b"private-response"
            assert urllib.request._opener is None
            assert "multi_search_mcp" in str(http.__file__)
            print("no-host-opener-ok")
            """
        )
        self.assertIn("no-host-opener-ok", output)


if __name__ == "__main__":
    unittest.main()
