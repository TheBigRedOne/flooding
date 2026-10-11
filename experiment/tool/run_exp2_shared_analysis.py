#!/usr/bin/env python3
"""Host-side Exp2-A summary. Does not start a VM or modify main-experiment metrics."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List, Sequence

import mobility_event_metrics as metrics
import run_mobility_event_analysis as decoder

import exp2_shared_config as config
import exp2_shared_metrics as exp2


def _read_log(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def analyze_directory(run_dir: Path) -> tuple[List[Dict[str, object]], str]:
    params = run_dir / "params.txt"
    active = config.read_active_consumers(params)
    missing = config.missing_evidence(run_dir, active)
    if missing:
        detail = "\n".join(f"required Exp2 evidence missing: {run_dir / name}" for name in missing)
        raise SystemExit(detail)
    packets_path = run_dir / "mobility_packets.csv"
    decoder.decode_run(run_dir, packets_path)
    packets = metrics.load_packets(str(packets_path))
    handoffs = metrics.load_handoffs(str(run_dir / "handoffs.txt"))
    _segments, interval = metrics.load_run_config(str(params))
    validation = {
        consumer: exp2.parse_validation_log(_read_log(run_dir / f"{consumer}.log"))
        for consumer in active
    }
    rows, audits = exp2.observe_run(packets, handoffs, active, validation, frame_period_ms=interval)
    inactive = [host for host in config.CONSUMER_HOSTS if host not in active]
    silent = exp2.inactive_consumer_application_traffic(packets, inactive)
    lines = [
        f"active_consumers={','.join(active)}",
        f"stream_prefix={config.STREAM_PREFIX}",
        f"guard_name={config.GUARD_NAME}",
        "consumer_observed_recovery_ms is handoff to the first post-handoff content Data.",
        "confirmed_producer_recovery_ms is set only when the producer egress capture shows that Data after the handoff.",
        "interest_to_data_ms is request completion latency and is not the handoff recovery time.",
        "network_recovery_flood_bytes counts each sender-egress flood transmission once.",
    ]
    lines.extend(audits)
    lines.extend(silent)
    for row in rows:
        lines.append(
            f"{row['consumer']} h{row['handoff_index']} origin={row['origin']} "
            f"observed_ms={row['consumer_observed_recovery_ms']} "
            f"confirmed_ms={row['confirmed_producer_recovery_ms']} "
            f"validation={row['validation']} name={row['content_name']}"
        )
        if row["origin"] == "absent" or row["validation"] == "failure":
            lines.append(f"retained failure: {row['consumer']} h{row['handoff_index']} {row['audit']}")
    return rows, "\n".join(lines) + "\n"


def write_outputs(run_dir: Path, rows: Sequence[Dict[str, object]], summary: str) -> None:
    destination = run_dir / "exp2_observations.csv"
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(exp2.OBSERVATION_FIELDS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (run_dir / "exp2_summary.txt").write_text(summary, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if len(arguments) != 1:
        raise SystemExit("usage: run_exp2_shared_analysis.py <run-directory>")
    run_dir = Path(arguments[0])
    rows, summary = analyze_directory(run_dir)
    write_outputs(run_dir, rows, summary)
    print(summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
