#!/usr/bin/env python3
"""Run terminology and format checks independently; do not modify sources."""
from pathlib import Path
import subprocess
import sys


def main() -> int:
    here = Path(__file__).resolve().parent
    paths = sys.argv[1:] or [str(here.parent / "main.tex")]
    codes = []
    for checker in ["check_terminology.py", "check_format.py"]:
        print(f"=== {checker} ===", flush=True)
        codes.append(subprocess.run([sys.executable, str(here / checker), *paths]).returncode)
    # Configuration/execution failure takes precedence; warnings alone stay zero.
    return 2 if any(c not in (0, 1) for c in codes) else int(1 in codes)


if __name__ == "__main__":
    raise SystemExit(main())
