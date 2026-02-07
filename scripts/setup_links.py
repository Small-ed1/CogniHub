from __future__ import annotations

import os
from pathlib import Path


def _prompt(question: str, default: str | None = None) -> str:
    if default:
        q = f"{question} [{default}]: "
    else:
        q = f"{question}: "
    ans = input(q).strip()
    return ans or (default or "")


def _prompt_bool(question: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    ans = input(f"{question} ({d}): ").strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes", "true", "1"}


def _safe_symlink(link_path: Path, target_path: Path) -> None:
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_symlink() and link_path.resolve() == target_path.resolve():
            print(f"OK  {link_path} already points to {target_path}")
            return
        print(f"SKIP {link_path} already exists (won't overwrite)")
        return

    if not target_path.exists():
        print(f"SKIP target does not exist: {target_path}")
        return

    link_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        link_path.symlink_to(target_path, target_is_directory=target_path.is_dir())
        print(f"OK  created {link_path} -> {target_path}")
    except OSError as e:
        print(f"WARN could not create symlink: {link_path} -> {target_path} ({e})")
        if os.name == "nt":
            print("Tip: On Windows, enable Developer Mode or run as Administrator to create symlinks.")


def main() -> int:
    print("ContextHarbor symlink helper")
    print("This creates optional convenience links in your home directory.")
    print("It will NOT overwrite existing files.")
    print("")

    home = Path.home()

    if _prompt_bool("Create ~/zims symlink?", default=False):
        target = Path(os.path.expanduser(_prompt("Path to your ZIM directory", ""))).expanduser()
        _safe_symlink(home / "zims", target)

    if _prompt_bool("Create ~/Ebooks symlink?", default=False):
        target = Path(os.path.expanduser(_prompt("Path to your ebooks directory", ""))).expanduser()
        _safe_symlink(home / "Ebooks", target)

    print("")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
