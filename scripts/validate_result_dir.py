#!/usr/bin/env python3
"""Validate required files in one experiment result directory.

Purpose:
    Check whether a result directory contains the raw files required by the
    host-side analysis pipeline.

Interface:
    python3 scripts/validate_result_dir.py --result-dir <dir> [--require-params]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List


REQUIRED_RESULT_FILES = (
    "consumer_capture.csv",
    "network_overhead.csv",
)
PARAMS_FILE = "params.txt"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for result-directory validation."""
    parser = argparse.ArgumentParser(
        description="Validate required files in one experiment result directory."
    )
    parser.add_argument(
        "--result-dir",
        required=True,
        help="Directory containing one collected experiment result set.",
    )
    parser.add_argument(
        "--require-params",
        action="store_true",
        help="Require params.txt in addition to the common CSV inputs.",
    )
    return parser.parse_args()


def collect_missing_files(result_dir: Path, require_params: bool) -> List[str]:
    """Return missing required file names for the given result directory."""
    required_files: Iterable[str] = REQUIRED_RESULT_FILES
    missing = [name for name in required_files if not (result_dir / name).is_file()]
    if require_params and not (result_dir / PARAMS_FILE).is_file():
        missing.append(PARAMS_FILE)
    return missing


def main() -> int:
    """Validate the directory and report missing files through the exit code."""
    args = parse_args()
    result_dir = Path(args.result_dir)
    if not result_dir.is_dir():
        print(f"Missing result directory: {result_dir}")
        return 1

    missing = collect_missing_files(result_dir, args.require_params)
    if missing:
        print(f"Missing required files in {result_dir}: {', '.join(missing)}")
        return 1

    print(f"Validated result directory: {result_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
