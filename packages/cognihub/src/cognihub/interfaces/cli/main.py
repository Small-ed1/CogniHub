"""Compatibility wrapper for the CogniHub CLI.

The implementation lives in `cognihub.cli.main`.
"""

from __future__ import annotations

from cognihub.cli.main import CogniHubCLI, run_one_shot, run_repl

__all__ = ["CogniHubCLI", "run_one_shot", "run_repl"]
