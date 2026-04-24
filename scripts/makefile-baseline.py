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


def emit_workflow_recipe(
    *,
    vagrant_dir: str,
    host_alias: str,
    ssh_config_var: str,
    box_env_name: str,
    box_path: str,
    experiment_subdir: str,
    local_results_dir: str,
    clear_local_results: bool,
    remote_make_command: str,
) -> list[str]:
    """Emit the host-side VM workflow recipe lines for one experiment run."""
    clear_line = f'\trm -rf "{local_results_dir}"/*' if clear_local_results else None
    return [
        f'\t@echo "*** Running experiment VM workflow: {experiment_subdir} ($(PROVIDER), dir={vagrant_dir})"',
        f'\tenv "{box_env_name}={box_path}" VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD={vagrant_dir} vagrant up --provision',
        f'\tVAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD={vagrant_dir} vagrant ssh-config --host {host_alias} > {ssh_config_var}',
        f'\trsync -avH -e "ssh -F {ssh_config_var}" --exclude .git --exclude .vagrant --exclude results --exclude paper/bin ./ {host_alias}:$(REMOTE_DIR)/',
        *([clear_line] if clear_line is not None else []),
        (
            f'\tVAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD={vagrant_dir} vagrant ssh -c '
            f'"set -e; cd $(REMOTE_DIR)/{experiment_subdir} && make clean && {remote_make_command}; '
            'mkdir -p results/minindn-logs; '
            'if [ -d /tmp/minindn ]; then '
            'for name in $(MOBILITY_LOG_NODES); do '
            'node=/tmp/minindn/$$name; '
            'if [ -d \\"$$node/log\\" ]; then '
            'mkdir -p \\"results/minindn-logs/$$name\\"; '
            'cp -f \\"$$node/log/nfd.log\\" \\"results/minindn-logs/$$name/\\" 2>/dev/null || true; '
            'cp -f \\"$$node/log/nlsr.log\\" \\"results/minindn-logs/$$name/\\" 2>/dev/null || true; '
            'fi; '
            'done; '
            'fi"'
        ),
        f'\trsync -avH -e "ssh -F {ssh_config_var}" "{host_alias}:$(REMOTE_DIR)/{experiment_subdir}/results/." "{local_results_dir}/"',
        f'\tVAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD={vagrant_dir} vagrant halt -f || true',
        '\t@echo ""',
        f'\t@echo "*** Finished experiment VM workflow: {experiment_subdir} ($(PROVIDER), dir={vagrant_dir})"',
        '\t@echo ""',
    ]


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
        f"{' '.join(raw_targets)} &: $(APP_SRCS) $(BASELINE_SRCS) $(EXPERIMENT_TOOL_SRCS) $(PIPELINE_CONFIG_SRCS) box/baseline/baseline.$(PROVIDER).box | {profile_dir} {profile_dir}/pcap_nodes",
        *emit_workflow_recipe(
            vagrant_dir="experiment/baseline",
            host_alias="baseline",
            ssh_config_var="$(BASELINE_SSH_CONFIG)",
            box_env_name="ACTUAL_BASELINE_BOX_PATH",
            box_path="box/baseline/baseline.$(PROVIDER).box",
            experiment_subdir="experiment/baseline",
            local_results_dir=profile_dir,
            clear_local_results=True,
            remote_make_command=(
                f"NLSR_HELLO_INTERVAL='{hello}' "
                f"NLSR_ADJ_LSA_BUILD_INTERVAL='{adj}' "
                f"NLSR_ROUTING_CALC_INTERVAL='{route}' "
                f"NLSR_TUNING_PROFILE='{Path(profile_dir).name}' make all"
            ),
        ),
        "",
    ]


def emit_data_rules(profile: str, assignments: dict[str, str]) -> list[str]:
    """Emit host-side CSV derivation rules for one baseline profile."""
    profile_dir = assignments[f"BASELINE_PROFILE_DIR_{profile}"]
    return [
        f"{profile_dir}/consumer_capture.csv: {profile_dir}/consumer_capture.pcap",
        '\ttshark -r "$<" -T fields -e frame.time_epoch -e frame.len -e ndn.type -e ndn.name -E separator=, -E header=y -E quote=d > "$@"',
        "",
        f"{profile_dir}/network_overhead.csv: {' '.join(node_pcap_paths(profile_dir))} $(OVERHEAD_EXTRACT_SCRIPT)",
        f'\t$(PYTHON) $(OVERHEAD_EXTRACT_SCRIPT) --pcap-dir "{profile_dir}/pcap_nodes" --output "$@"',
        "",
    ]


def emit_compare_rules(profile: str, assignments: dict[str, str]) -> list[str]:
    """Emit host-side comparison-only plotting rules for one non-default profile."""
    profile_dir = assignments[f"BASELINE_PROFILE_DIR_{profile}"]
    return [
        f"{profile_dir}/disruption_times.pdf: {profile_dir}/consumer_capture.csv $(PLOT_LATENCY_SCRIPT) | $(VENV_DIR)",
        f'\t$(PYTHON) $(PLOT_LATENCY_SCRIPT) --input "{profile_dir}/consumer_capture.csv" --plot-output "$@" --handoff-times "120, 240"',
        "",
        f"{profile_dir}/disruption_metrics.txt: {profile_dir}/consumer_capture.csv $(PLOT_LATENCY_SCRIPT) | $(VENV_DIR)",
        f'\t$(PYTHON) $(PLOT_LATENCY_SCRIPT) --input "{profile_dir}/consumer_capture.csv" --metrics-output "$@" --handoff-times "120, 240"',
        "",
        f"{profile_dir}/overhead_timeseries.pdf: {profile_dir}/network_overhead.csv $(PLOT_OVERHEAD_SCRIPT) | $(VENV_DIR)",
        f'\t$(PYTHON) $(PLOT_OVERHEAD_SCRIPT) --input "{profile_dir}/network_overhead.csv" --timeseries-output "$@" --handoff-times "120, 240"',
        "",
        f"{profile_dir}/overhead_summary.pdf: {profile_dir}/network_overhead.csv $(PLOT_OVERHEAD_SCRIPT) | $(VENV_DIR)",
        f'\t$(PYTHON) $(PLOT_OVERHEAD_SCRIPT) --input "{profile_dir}/network_overhead.csv" --summary-output "$@" --handoff-times "120, 240"',
        "",
        f"{profile_dir}/overhead_total.txt: {profile_dir}/network_overhead.csv $(PLOT_OVERHEAD_SCRIPT) | $(VENV_DIR)",
        f'\t$(PYTHON) $(PLOT_OVERHEAD_SCRIPT) --input "{profile_dir}/network_overhead.csv" --metrics-output "$@" --handoff-times "120, 240"',
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
