#!/usr/bin/env python3
"""
Convert per-node OptoFlood pcaps into a unified packet-level CSV.

The output CSV is the single analysis input for network-overhead plots.
Each row represents one decoded packet observation on one node.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


CSV_FIELDS: List[str] = [
    "frame.number",
    "frame.time_epoch",
    "frame.len",
    "sll.pkttype",
    "sll.ifindex",
    "ndn.type",
    "ndn.name",
    "ndn.flood_id",
    "ndn.new_face_seq",
    "ndn.lp.hoplimit",
    "ndn.lp.mobility_flag",
    "ndn.hoplimit",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract a unified OptoFlood overhead CSV from per-node pcaps."
    )
    parser.add_argument(
        "--pcap-dir",
        required=True,
        help="Directory containing per-node *.pcap files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output CSV path.",
    )
    parser.add_argument(
        "--lua-script",
        default=str(Path(__file__).with_name("ndn.lua")),
        help="Path to the custom NDN Lua dissector.",
    )
    parser.add_argument(
        "--tshark",
        default="tshark",
        help="Path to tshark executable.",
    )
    return parser.parse_args()


def build_tshark_cmd(tshark: str, lua_script: str, pcap_path: Path) -> List[str]:
    cmd = [tshark]
    if not os.path.exists(lua_script):
        raise FileNotFoundError(f"Lua dissector not found: {lua_script}")
    cmd += ["-X", f"lua_script:{lua_script}"]
    cmd += ["-r", str(pcap_path), "-T", "fields"]
    for field in CSV_FIELDS:
        cmd += ["-e", field]
    cmd += [
        "-E",
        "separator=,",
        "-E",
        "header=n",
        "-E",
        "quote=d",
        "-E",
        "occurrence=f",
    ]
    return cmd


def iter_pcaps(pcap_dir: Path) -> Iterable[Path]:
    return sorted(pcap_dir.glob("*.pcap"))


def extract_rows(tshark: str, lua_script: str, pcap_path: Path) -> List[str]:
    cmd = build_tshark_cmd(tshark, lua_script, pcap_path)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"tshark failed for {pcap_path}: {result.stderr.strip() or 'unknown error'}"
        )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    args = parse_args()

    pcap_dir = Path(args.pcap_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pcaps = list(iter_pcaps(pcap_dir))
    header = ["node", *CSV_FIELDS]

    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        output_file.write(",".join(f'"{field}"' for field in header) + "\n")

        if not pcaps:
            print(f"Warning: no node pcaps found under {pcap_dir}", file=sys.stderr)
            return 0

        for pcap_path in pcaps:
            node_name = pcap_path.stem
            for row in extract_rows(args.tshark, args.lua_script, pcap_path):
                output_file.write(f'"{node_name}",{row}\n')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
