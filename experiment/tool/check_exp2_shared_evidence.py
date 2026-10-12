#!/usr/bin/env python3
"""Host-side Exp2-A evidence check. Does not start a VM or compute summary metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import exp2_shared_config as config


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: check_exp2_shared_evidence.py <run-directory>", file=sys.stderr)
        return 2
    run_dir = Path(arguments[0])
    problems = config.inspect_run(run_dir)
    if problems:
        print(f"Exp2 evidence check failed: {run_dir}")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"Exp2 evidence check passed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
