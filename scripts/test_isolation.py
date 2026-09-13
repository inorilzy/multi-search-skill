"""Disposable runtime and network isolation for the repository test runners.

The module deliberately has no imports from the product package.  The standard
test runner imports it before test discovery so user configuration and state
paths are redirected before any product module is loaded.  A temporary
``sitecustomize`` installed by :func:`isolated_test_environment` activates the
same network guard in Python child processes.
"""
from __future__ import annotations

import atexit
import contextlib
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from typing import Iterator, Mapping
import urllib.parse
import urllib.request
from unittest.mock import patch


ISOLATION_ENV = "MULTI_SEARCH_TEST_ISOLATION"
REPORT_ENV = "MULTI_SEARCH_TEST_ISOLATION_REPORT"

KEY_ENV_NAMES = (
    "BRAVE_SEARCH_API_KEY", "BRAVE_API_KEY", "PARALLEL_API_KEY",
    "BAIDU_QIANFAN_API_KEY", "QIANFAN_API_KEY", "APPBUILDER_API_KEY",
    "TAVILY_API_KEY", "EXA_API_KEY", "JINA_API_KEY", "JINA_KEY",
    "GITHUB_TOKEN", "GH_TOKEN", "FIRECRAWL_API_KEY", "SERPAPI_API_KEY",
    "SERPAPI_KEY", "TWITTER_COOKIES_PATH",
)

_PROXY_ENV_NAMES = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY", "http_proxy",
    "https_proxy", "all_proxy", "ftp_proxy", "PROXY",
)
_NO_PROXY_ENV_NAMES = ("NO_PROXY", "no_proxy")
_LOCAL_HOST_NAMES = {"localhost", "localhost.localdomain"}


class NetworkIsolationError(RuntimeError):
    """Raised when a test attempts network access outside the loopback host."""


@dataclass(frozen=True)
class IsolationPaths:
    """Paths made disposable for one runner invocation."""

    root: Path
    home: Path
    config: Path
    keys: Path
    state: Path
    report: Path


_ACTIVE_GUARD: "NetworkGuard | None" = None
_CHILD_GUARD: "NetworkGuard | None" = None


def active_guard() -> "NetworkGuard | None":
    """Return the guard active in this interpreter, if any."""

    return _ACTIVE_GUARD


def _host_text(host) -> str:
    if isinstance(host, bytes):
        return host.decode("ascii", errors="ignore")
    return str(host)


def _is_loopback_host(host) -> bool:
    if host is None:
        return True
    value = _host_text(host).strip().rstrip(".").lower()
    if not value:
        return True
    if value in _LOCAL_HOST_NAMES:
        return True
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def _socket_host(address):
    """Get an INET host from a socket address; UNIX paths are not network egress."""

    if isinstance(address, tuple) and address:
        return address[0]
    return None


class NetworkGuard:
    """Block non-loopback DNS and socket/urllib network operations.

    A denied operation is recorded before the exception is raised.  Recording
    is also written to the runner report file so a child process that catches
    the exception cannot make the parent suite appear clean.
    """

    def __init__(
        self,
        report_path: str | Path | None = None,
        *,
        child_environment: Mapping[str, str] | None = None,
        child_pythonpath: str = "",
    ):
        report_value = report_path or os.environ.get(REPORT_ENV)
        self.report_path = Path(report_value) if report_value else None
        self._child_environment = dict(child_environment or {})
        self._child_pythonpath = child_pythonpath
        self._violations: list[str] = []
        self._patchers = []
        self._previous_guard: "NetworkGuard | None" = None
        self._installed = False
        self._guarded_create_connection = None
        self._report_lock = threading.Lock()

    @property
    def violations(self) -> tuple[str, ...]:
        return tuple(self._violations)

    @property
    def violation_count(self) -> int:
        return len(self._violations)

    def __enter__(self) -> "NetworkGuard":
        self.install()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.uninstall()

    def install(self) -> None:
        global _ACTIVE_GUARD
        if self._installed:
            return
        self._previous_guard = _ACTIVE_GUARD

        def guarded_getaddrinfo(host, port, *args, **kwargs):
            if not _is_loopback_host(host):
                self._deny("socket.getaddrinfo")
            return original_getaddrinfo(host, port, *args, **kwargs)

        def guarded_gethostbyname(host):
            if not _is_loopback_host(host):
                self._deny("socket.gethostbyname")
            return original_gethostbyname(host)

        def guarded_gethostbyname_ex(host):
            if not _is_loopback_host(host):
                self._deny("socket.gethostbyname_ex")
            return original_gethostbyname_ex(host)

        def guarded_gethostbyaddr(host):
            if not _is_loopback_host(host):
                self._deny("socket.gethostbyaddr")
            return original_gethostbyaddr(host)

        def guarded_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                                       source_address=None, *args, **kwargs):
            self._check_socket_address(address, "socket.create_connection")
            return original_create_connection(
                address, timeout=timeout, source_address=source_address, *args, **kwargs,
            )

        def guarded_connect(sock, address):
            self._check_socket_address(address, "socket.connect")
            return original_connect(sock, address)

        def guarded_connect_ex(sock, address):
            self._check_socket_address(address, "socket.connect_ex")
            return original_connect_ex(sock, address)

        def guarded_sendto(sock, data, *args, **kwargs):
            address = kwargs.get("address")
            if address is None:
                if len(args) == 1:
                    address = args[0]
                elif len(args) >= 2:
                    address = args[1]
            if address is not None:
                self._check_socket_address(address, "socket.sendto")
            return original_sendto(sock, data, *args, **kwargs)

        def guarded_proxy_open(handler, request, proxy, proxy_type):
            scheme, host = self._url_target(request, boundary="urllib.proxy")
            if (
                scheme in {"http", "https"}
                and not _is_loopback_host(host)
                and not self._transport_is_replaced()
            ):
                self._deny("urllib.proxy")
            return original_proxy_open(handler, request, proxy, proxy_type)

        original_getaddrinfo = socket.getaddrinfo
        original_gethostbyname = socket.gethostbyname
        original_gethostbyname_ex = socket.gethostbyname_ex
        original_gethostbyaddr = socket.gethostbyaddr
        original_create_connection = socket.create_connection
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_sendto = socket.socket.sendto
        original_popen = subprocess.Popen
        original_proxy_open = urllib.request.ProxyHandler.proxy_open
        while hasattr(original_popen, "_test_isolation_original"):
            original_popen = original_popen._test_isolation_original

        class GuardedPopen(original_popen):
            _test_isolation_original = original_popen

            def __init__(self, *args, **kwargs):
                child_env = dict(os.environ if kwargs.get("env") is None else kwargs["env"])
                self._guard._prepare_child_environment(child_env)
                kwargs["env"] = child_env
                super().__init__(*args, **kwargs)

            _guard = self

        guarded_popen = GuardedPopen

        self._guarded_create_connection = guarded_create_connection
        self._patchers = [
            patch.object(socket, "getaddrinfo", guarded_getaddrinfo),
            patch.object(socket, "gethostbyname", guarded_gethostbyname),
            patch.object(socket, "gethostbyname_ex", guarded_gethostbyname_ex),
            patch.object(socket, "gethostbyaddr", guarded_gethostbyaddr),
            patch.object(socket, "create_connection", guarded_create_connection),
            patch.object(socket.socket, "connect", guarded_connect),
            patch.object(socket.socket, "connect_ex", guarded_connect_ex),
            patch.object(socket.socket, "sendto", guarded_sendto),
            patch.object(urllib.request.ProxyHandler, "proxy_open", guarded_proxy_open),
            patch.object(subprocess, "Popen", guarded_popen),
        ]
        if hasattr(urllib.request, "getproxies_registry"):
            self._patchers.append(
                patch.object(urllib.request, "getproxies_registry", lambda: {})
            )
        if hasattr(socket.socket, "sendmsg"):
            original_sendmsg = socket.socket.sendmsg

            def guarded_sendmsg(sock, buffers, ancdata=(), flags=0, address=None, *args, **kwargs):
                if address is not None:
                    self._check_socket_address(address, "socket.sendmsg")
                return original_sendmsg(sock, buffers, ancdata, flags, address, *args, **kwargs)

            self._patchers.append(patch.object(socket.socket, "sendmsg", guarded_sendmsg))

        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            curl_requests = None
        if curl_requests is not None:
            original_curl_request = curl_requests.Session.request

            def guarded_curl_request(session, method, url, *args, **kwargs):
                scheme, host = self._url_target(url, boundary="curl_cffi.request")
                if scheme in {"http", "https"} and not _is_loopback_host(host):
                    self._deny("curl_cffi.request")
                return original_curl_request(session, method, url, *args, **kwargs)

            self._patchers.append(
                patch.object(curl_requests.Session, "request", guarded_curl_request)
            )

        try:
            for patcher in self._patchers:
                patcher.start()
        except BaseException:
            for patcher in reversed(self._patchers):
                patcher.stop()
            self._patchers = []
            raise
        self._installed = True
        _ACTIVE_GUARD = self

    def uninstall(self) -> None:
        global _ACTIVE_GUARD
        if not self._installed:
            return
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers = []
        self._installed = False
        _ACTIVE_GUARD = self._previous_guard

    def assert_clean(self) -> None:
        report_violations = self._report_violations()
        count = report_violations if self.report_path is not None else len(self._violations)
        if count:
            raise NetworkIsolationError(
                f"test isolation blocked {count} unexpected network operation(s)"
            )

    def _report_violations(self) -> int:
        if self.report_path is None or not self.report_path.exists():
            return 0
        try:
            return sum(1 for line in self.report_path.read_text(encoding="utf-8").splitlines() if line)
        except OSError as exc:
            raise NetworkIsolationError("test isolation could not read its violation report") from exc

    def _record(self, boundary: str) -> None:
        self._violations.append(boundary)
        if self.report_path is None:
            return
        try:
            with self._report_lock:
                with self.report_path.open("a", encoding="utf-8", newline="\n") as report:
                    report.write(boundary + "\n")
        except OSError as exc:
            raise NetworkIsolationError("test isolation could not record a network violation") from exc

    def _deny(self, boundary: str) -> None:
        self._record(boundary)
        raise NetworkIsolationError(f"test isolation blocked external network at {boundary}")

    def _check_socket_address(self, address, boundary: str) -> None:
        host = _socket_host(address)
        if host is not None and not _is_loopback_host(host):
            self._deny(boundary)

    def _url_target(self, target, *, boundary: str = "urllib.proxy") -> tuple[str, str | None]:
        url = getattr(target, "full_url", target)
        try:
            parsed = urllib.parse.urlsplit(str(url))
        except ValueError:
            self._deny(boundary)
        return parsed.scheme.lower(), parsed.hostname

    def _transport_is_replaced(self) -> bool:
        return socket.create_connection is not self._guarded_create_connection

    def _prepare_child_environment(self, child_env: dict[str, str]) -> None:
        # Force the home/config roots and guard markers even when a test passes
        # a hand-built env mapping.  Explicit provider/config values are left
        # intact so a test may still inject a synthetic credential or config.
        for name in (
            "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA",
            "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
        ):
            if name in self._child_environment:
                child_env[name] = self._child_environment[name]
        for name, value in self._child_environment.items():
            child_env.setdefault(name, value)
        inherited = child_env.get("PYTHONPATH", "")
        paths = [item for item in (self._child_pythonpath, inherited) if item]
        child_env["PYTHONPATH"] = os.pathsep.join(paths)
        child_env[ISOLATION_ENV] = "1"
        if self.report_path is not None:
            child_env[REPORT_ENV] = str(self.report_path)


@dataclass(frozen=True)
class IsolatedTestEnvironment:
    """The disposable paths and guard for one runner invocation."""

    paths: IsolationPaths
    guard: NetworkGuard

    @property
    def root(self) -> Path:
        return self.paths.root

    @property
    def home(self) -> Path:
        return self.paths.home

    @property
    def config(self) -> Path:
        return self.paths.config

    @property
    def keys(self) -> Path:
        return self.paths.keys

    @property
    def state(self) -> Path:
        return self.paths.state

    @property
    def report(self) -> Path:
        return self.paths.report

    def assert_clean(self) -> None:
        self.guard.assert_clean()


def activate_from_environment() -> NetworkGuard | None:
    """Activate a child-process guard when the runner environment requests it."""

    global _CHILD_GUARD
    if os.environ.get(ISOLATION_ENV) != "1":
        return None
    if _CHILD_GUARD is None:
        _CHILD_GUARD = NetworkGuard()
        _CHILD_GUARD.install()
        atexit.register(_CHILD_GUARD.uninstall)
    return _CHILD_GUARD


def _isolated_environment_changes(paths: IsolationPaths, *, pythonpath: str) -> dict[str, str]:
    home = str(paths.home)
    drive, tail = os.path.splitdrive(home)
    changes = {
        "HOME": home,
        "USERPROFILE": home,
        "HOMEDRIVE": drive,
        "HOMEPATH": tail or os.path.sep,
        "APPDATA": str(paths.home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(paths.home / "AppData" / "Local"),
        "XDG_CONFIG_HOME": str(paths.home / ".config"),
        "XDG_DATA_HOME": str(paths.home / ".local" / "share"),
        "XDG_STATE_HOME": str(paths.home / ".local" / "state"),
        # Leave the config selector unset so the normal user-config precedence
        # is exercised against the disposable home rather than as an explicit
        # path.  Tests that inject MULTI_SEARCH_CONFIG remain free to do so.
        "MULTI_SEARCH_CONFIG": "",
        ISOLATION_ENV: "1",
        REPORT_ENV: str(paths.report),
        "PYTHONPATH": pythonpath,
    }
    changes.update({name: "" for name in KEY_ENV_NAMES})
    changes.update({name: "" for name in _PROXY_ENV_NAMES})
    changes.update({name: "" for name in _NO_PROXY_ENV_NAMES})
    return changes


def _write_sitecustomize(path: Path) -> None:
    path.write_text(
        "import sys\n"
        "import test_isolation as _test_isolation\n"
        "sys.modules.setdefault('scripts.test_isolation', _test_isolation)\n"
        "_test_isolation.activate_from_environment()\n",
        encoding="utf-8",
    )


@contextlib.contextmanager
def isolated_test_environment(
    *,
    source_root: str | Path | None = None,
    prefix: str = "multi-search-tests-",
    include_inherited_pythonpath: bool = True,
) -> Iterator[IsolatedTestEnvironment]:
    """Run code with disposable config/credentials and a loopback-only network.

    ``source_root`` is added to child ``PYTHONPATH`` for the source-tree test
    runner.  Installation smoke tests leave it unset so their child imports
    continue to resolve the non-editable package from ``site-packages``.
    """

    script_root = Path(__file__).resolve().parent
    source_path = Path(source_root).resolve() if source_root is not None else None
    inherited = os.environ.get("PYTHONPATH") if include_inherited_pythonpath else None

    with tempfile.TemporaryDirectory(prefix=prefix) as temp:
        temp_root = Path(temp)
        home = temp_root / "home"
        home.mkdir()
        (home / ".multi-search").mkdir()
        (home / "AppData" / "Roaming").mkdir(parents=True)
        (home / "AppData" / "Local").mkdir(parents=True)
        (home / ".config").mkdir()
        (home / ".local" / "share").mkdir(parents=True)
        (home / ".local" / "state").mkdir(parents=True)

        config_path = home / ".multi-search" / "multi-search-config.json"
        keys_path = home / ".search-keys.json"
        state_path = home / ".multi-search" / "state.sqlite"
        report_path = temp_root / "network-violations.log"
        config_path.write_text("{}\n", encoding="utf-8")
        keys_path.write_text("{}\n", encoding="utf-8")
        report_path.touch()

        bootstrap = temp_root / "bootstrap"
        bootstrap.mkdir()
        _write_sitecustomize(bootstrap / "sitecustomize.py")

        pythonpath = [str(bootstrap), str(script_root)]
        if source_path is not None:
            pythonpath.append(str(source_path))
        if inherited:
            pythonpath.append(inherited)

        paths = IsolationPaths(
            root=temp_root,
            home=home,
            config=config_path,
            keys=keys_path,
            state=state_path,
            report=report_path,
        )
        child_pythonpath = os.pathsep.join(pythonpath)
        changes = _isolated_environment_changes(paths, pythonpath=child_pythonpath)
        child_environment = {
            key: value for key, value in changes.items() if key != "PYTHONPATH"
        }
        with patch.dict(os.environ, changes):
            with NetworkGuard(
                report_path,
                child_environment=child_environment,
                child_pythonpath=child_pythonpath,
            ) as guard:
                yield IsolatedTestEnvironment(paths, guard)
