"""Smoke tests for KiwixTools against a real kiwix-serve.

These tests are optional and will be skipped if kiwix-serve (or a small ZIM)
is not available in the local environment.
"""

import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional

import pytest
import requests

from ollama_cli.tools.kiwix_tools import KiwixTools


def _free_port() -> int:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def _wait_http(url: str, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    last_err: Optional[Exception] = None
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=0.5)
            if r.status_code < 500:
                return
        except Exception as e:
            last_err = e
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_err}")


@pytest.mark.skipif(shutil.which("kiwix-serve") is None, reason="kiwix-serve not installed")
def test_kiwix_suggest_and_open_with_real_server() -> None:
    # Use a small ZIM for predictable startup and request latency.
    src_zim = os.getenv("KIWIX_TEST_ZIM")
    if not src_zim:
        pytest.skip("KIWIX_TEST_ZIM not set")
    if not os.path.exists(src_zim):
        pytest.skip(f"KIWIX_TEST_ZIM not found: {src_zim}")

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory() as tmp:
        # kiwix-serve expects the ZIM to be listed in the library.
        lib_path = os.path.join(tmp, "library.xml")
        with open(lib_path, "w", encoding="utf-8") as f:
            f.write(
                "<library version=\"20110515\">\n"
                f"  <book id=\"test\" path=\"{src_zim}\" title=\"Test\" name=\"test\" />\n"
                "</library>\n"
            )

        proc = subprocess.Popen(
            [
                "kiwix-serve",
                "--port",
                str(port),
                "--library",
                lib_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            _wait_http(base_url + "/")

            kt = KiwixTools(kiwix_url=base_url, timeout=10)
            suggestions = kt.suggest("python", "async", count=3)
            assert isinstance(suggestions, list)
            assert len(suggestions) >= 1
            assert "path" in suggestions[0]

            first_path = suggestions[0]["path"]
            opened = kt.open_raw("test", first_path, max_chars=4000)
            assert opened["zim"] == "test"
            assert opened["path"] == first_path
            assert opened["content"]

        finally:
            proc.terminate()
            proc.wait(timeout=10)


def test_kiwix_list_zims_from_directory() -> None:
    src_zim = os.getenv("KIWIX_TEST_ZIM")
    if not src_zim:
        pytest.skip("KIWIX_TEST_ZIM not set")
    if not os.path.exists(src_zim):
        pytest.skip(f"KIWIX_TEST_ZIM not found: {src_zim}")

    with tempfile.TemporaryDirectory() as tmp:
        # Keep listing fast by using a temp directory.
        os.symlink(src_zim, os.path.join(tmp, "python.zim"))
        with open(os.path.join(tmp, "library.xml"), "w", encoding="utf-8") as f:
            f.write(
                "<library version=\"20110515\">\n"
                "  <book id=\"test\" path=\"python.zim\" title=\"Python\" description=\"Docs\" language=\"eng\" />\n"
                "</library>\n"
            )

        kt = KiwixTools(kiwix_url="http://127.0.0.1:1")
        zims = kt.list_zims(tmp)
        assert len(zims) == 1
        assert zims[0]["zim_id"] == "python"
        assert zims[0]["file_name"] == "python.zim"
        assert zims[0]["title"] == "Python"
