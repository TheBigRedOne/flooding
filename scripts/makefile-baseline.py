#!/usr/bin/env python3
"""Generate explicit host-side GNU Make rules for baseline experiment profiles.

Purpose:
    Expand the configured baseline profile set into explicit host-side rules so
    the main Makefile can include them without embedding repetitive rule blocks.

Interface:
    python3 scripts/makefile-baseline.py > Makefile.baseline
"""

from __future__ import annotations

import re
from pathlib import Path


ASSIGNMENT_RE = re.compile(r"^([A-Za-z0-9_]+)\s*:?=\s*(.*?)\s*$")
ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "experiment" / "tool" / "baseline_profiles.mk"


def load_assignments() -> dict[str, str]:
    """Load simple variable assignments from the baseline profile configuration."""
    assignments: dict[str, str] = {}
    for raw_line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT_RE.match(line)
        if match is None:
            continue
        assignments[match.group(1)] = match.group(2)
    return assignments


def node_pcap_paths(profile_dir: str) -> list[str]:
    """Return the raw per-node pcap targets for one result directory."""
    nodes = (
        "core",
        "agg1",
        "agg2",
        "acc1",
        "acc2",
        "acc3",
        "acc4",
        "acc5",
        "acc6",
        "producer",
        "consumer",
    )
    return [f"{profile_dir}/pcap_nodes/{node}.pcap" for node in nodes]


def emit_raw_rule(profile: str, assignments: dict[str, str]) -> list[str]:
    """Emit the grouped raw-output rule for one baseline profile."""
    profile_dir = assignments[f"BASELINE_PROFILE_DIR_{profile}"]
    hello = assignments[f"BASELINE_PROFILE_HELLO_{profile}"]
    adj = assignments[f"BASELINE_PROFILE_ADJ_{profile}"]
    route = assignments[f"BASELINE_PROFILE_ROUTE_{profile}"]
    raw_targets = [
        f"{profile_dir}/consumer_capture.pcap",
        *node_pcap_paths(profile_dir),
        f"{profile_dir}/params.txt",
    ]
    return [
        f"# Baseline profile: {profile}",
        f"{' '.join(raw_targets)} &: scripts/run-in-vm.sh box/baseline/baseline.$(PROVIDER).box $(APP_SRCS) $(BASELINE_SRCS) experiment/tool/exp.py experiment/tool/baseline_profiles.mk",
        (
            '\tRUN_IN_VM_CLEAR_LOCAL=1 '
            f'RUN_IN_VM_REMOTE_MAKE="NLSR_HELLO_INTERVAL=\'{hello}\' '
            f"NLSR_ADJ_LSA_BUILD_INTERVAL='{adj}' "
            f"NLSR_ROUTING_CALC_INTERVAL='{route}' "
            f"NLSR_TUNING_PROFILE='{Path(profile_dir).name}' make all\" "
            "sh $^ $@"
        ),
        "",
    ]


def emit_data_rules(profile: str, assignments: dict[str, str]) -> list[str]:
    """Emit host-side CSV derivation rules for one baseline profile."""
    profile_dir = assignments[f"BASELINE_PROFILE_DIR_{profile}"]
    return [
        f"{profile_dir}/consumer_capture.csv: {profile_dir}/consumer_capture.pcap experiment/tool/ndn.lua",
        '\ttshark -X lua_script:experiment/tool/ndn.lua -r "$<" -T fields -e frame.time_epoch -e frame.len -e ndn.type -e ndn.name -E separator=, -E header=y -E quote=d > "$@"',
        "",
        f"{profile_dir}/network_overhead.csv: experiment/tool/extract_overhead_csv.py {' '.join(node_pcap_paths(profile_dir))}",
        "\tpython3 $^ $@",
        "",
    ]


def emit_compare_rules(profile: str, assignments: dict[str, str]) -> list[str]:
    """Emit host-side comparison-only plotting rules for one non-default profile."""
    profile_dir = assignments[f"BASELINE_PROFILE_DIR_{profile}"]
    return [
        f"{profile_dir}/disruption_times.pdf: experiment/tool/plot_latency.py {profile_dir}/consumer_capture.csv",
        "\tpython3 $^ $@",
        "",
        f"{profile_dir}/disruption_metrics.txt: experiment/tool/plot_latency.py {profile_dir}/consumer_capture.csv",
        "\tpython3 $^ $@",
        "",
        f"{profile_dir}/overhead_timeseries.pdf: experiment/tool/plot_overhead.py {profile_dir}/network_overhead.csv",
        "\tpython3 $^ $@",
        "",
        f"{profile_dir}/overhead_summary.pdf: experiment/tool/plot_overhead.py {profile_dir}/network_overhead.csv",
        "\tpython3 $^ $@",
        "",
        f"{profile_dir}/overhead_total.txt: experiment/tool/plot_overhead.py {profile_dir}/network_overhead.csv",
        "\tpython3 $^ $@",
        "",
    ]


def main() -> int:
    """Print the generated baseline rules fragment to stdout."""
    assignments = load_assignments()
    profiles = assignments["BASELINE_PROFILE_IDS"].split()
    default_profile = assignments["BASELINE_DEFAULT_PROFILE"]

    lines = [
        "# Auto-generated file. Do not edit manually.",
        "# Source: scripts/makefile-baseline.py",
        "",
    ]
    for profile in profiles:
        lines.extend(emit_raw_rule(profile, assignments))
        lines.extend(emit_data_rules(profile, assignments))
        if profile != default_profile:
            lines.extend(emit_compare_rules(profile, assignments))

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
