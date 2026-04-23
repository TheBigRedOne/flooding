#!/usr/bin/env python3
"""Validate required files in one experiment result directory.

Purpose:
    Check whether a result directory contains the required raw or derived files
    for the host-side analysis pipeline.

Interface:
    python3 scripts/validate_result_dir.py --mode <raw|derived> --result-dir <dir>
        [--pcap-nodes <comma-separated-nodes>] [--require-params]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List


RAW_RESULT_FILES = (
    "consumer_capture.pcap",
)
DERIVED_RESULT_FILES = (
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
        "--mode",
        choices=("raw", "derived"),
        default="raw",
        help="Validation mode: raw experiment artifacts or derived CSV outputs.",
    )
    parser.add_argument(
        "--result-dir",
        required=True,
        help="Directory containing one collected experiment result set.",
    )
    parser.add_argument(
        "--pcap-nodes",
        help="Comma-separated node names expected under result-dir/pcap_nodes/ in raw mode.",
    )
    parser.add_argument(
        "--require-params",
        action="store_true",
        help="Require params.txt in addition to the common CSV inputs.",
    )
    return parser.parse_args()


def _parse_pcap_nodes(raw: str | None) -> List[str]:
    """Parse the expected per-node pcap file list from one comma-separated string."""
    if not raw:
        return []
    return [node.strip() for node in raw.split(",") if node.strip()]


def collect_missing_files(
    result_dir: Path,
    mode: str,
    require_params: bool,
    pcap_nodes: List[str],
) -> List[str]:
    """Return missing required file names for the given result directory."""
    required_files: Iterable[str] = RAW_RESULT_FILES if mode == "raw" else DERIVED_RESULT_FILES
    missing = [name for name in required_files if not (result_dir / name).is_file()]
    if mode == "raw":
        missing.extend(
            str(Path("pcap_nodes") / f"{node}.pcap")
            for node in pcap_nodes
            if not (result_dir / "pcap_nodes" / f"{node}.pcap").is_file()
        )
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

    missing = collect_missing_files(
        result_dir,
        args.mode,
        args.require_params,
        _parse_pcap_nodes(args.pcap_nodes),
    )
    if missing:
        print(f"Missing required files in {result_dir}: {', '.join(missing)}")
        return 1

    print(f"Validated result directory: {result_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
