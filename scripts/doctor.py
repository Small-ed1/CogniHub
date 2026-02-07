from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import pwd  # type: ignore
except Exception:  # pragma: no cover
    pwd = None  # type: ignore


def _ok(msg: str) -> None:
    print(f"OK  {msg}")


def _warn(msg: str) -> None:
    print(f"WARN {msg}")


def _err(msg: str) -> None:
    print(f"ERR {msg}")


def _env(name: str) -> str | None:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def _exists_dir(p: str) -> bool:
    path = Path(os.path.expanduser(p))
    return path.exists() and path.is_dir()


def _effective_home() -> Path:
    """Best-effort home directory for interactive use.

    If running under sudo, prefer the invoking user's home.
    """
    try:
        geteuid = getattr(os, "geteuid", None)
        uid = geteuid() if callable(geteuid) else None
        if pwd and isinstance(uid, int) and uid == 0:
            sudo_user = os.getenv("SUDO_USER")
            if sudo_user:
                getpwnam = getattr(pwd, "getpwnam", None)
                if callable(getpwnam):
                    info = getpwnam(sudo_user)
                    pw_dir = getattr(info, "pw_dir", None)
                    if isinstance(pw_dir, str) and pw_dir:
                        return Path(pw_dir)
    except Exception:
        pass
    return Path.home()


def _http_get(url: str, timeout_s: float = 2.0) -> tuple[bool, str]:
    try:
        import requests  # type: ignore
    except Exception:
        return (False, "requests not installed")

    try:
        r = requests.get(url, timeout=timeout_s)
        return (r.status_code < 500, f"HTTP {r.status_code}")
    except Exception as e:
        return (False, str(e))


def main() -> int:
    print("ContextHarbor doctor")
    print("")

    # Python
    _ok(f"python: {sys.version.split()[0]}")

    # Ollama
    ollama_url = _env("OLLAMA_URL") or "http://127.0.0.1:11434"
    ok, info = _http_get(ollama_url.rstrip("/") + "/api/version")
    if ok:
        _ok(f"ollama reachable: {ollama_url} ({info})")
    else:
        _warn(f"ollama not reachable: {ollama_url} ({info})")

    # Kiwix
    kiwix_url = _env("KIWIX_URL")
    if kiwix_url:
        ok, info = _http_get(kiwix_url.rstrip("/") + "/")
        if ok:
            _ok(f"kiwix reachable: {kiwix_url} ({info})")
        else:
            _warn(f"kiwix not reachable: {kiwix_url} ({info})")
    else:
        _warn("KIWIX_URL not set (offline Kiwix features disabled)")

    # ZIM directory
    home = _effective_home()

    zim_dir = _env("KIWIX_ZIM_DIR") or str(home / "zims")
    if _exists_dir(zim_dir):
        _ok(f"zim dir: {os.path.expanduser(zim_dir)}")
    else:
        _warn(f"zim dir missing: {os.path.expanduser(zim_dir)}")

    # EPUB directory
    ebooks_dir = _env("EBOOKS_DIR") or str(home / "Ebooks")
    if _exists_dir(ebooks_dir):
        _ok(f"ebooks dir: {os.path.expanduser(ebooks_dir)}")
    else:
        _warn(f"ebooks dir missing: {os.path.expanduser(ebooks_dir)}")

    print("")
    print("Tips:")
    print("- Generate .env:          python scripts/setup_env.py")
    print("- Optional symlinks:      python scripts/setup_links.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
