#!/usr/bin/env python3
"""Generate explicit host-side GNU Make rules for the solution experiment.

Purpose:
    Emit the host-side raw collection and derived-result rules for the solution
    experiment so the main Makefile can include them as explicit rules.

Interface:
    python3 scripts/makefile-solution.py > Makefile.solution
"""

from __future__ import annotations


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
    remote_make_command: str,
) -> list[str]:
    """Emit the host-side VM workflow recipe lines for one experiment run."""
    return [
        f'\t@echo "*** Running experiment VM workflow: {experiment_subdir} ($(PROVIDER), dir={vagrant_dir})"',
        f'\tenv "{box_env_name}={box_path}" VAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD={vagrant_dir} vagrant up --provision',
        f'\tVAGRANT_DEFAULT_PROVIDER=$(PROVIDER) VAGRANT_CWD={vagrant_dir} vagrant ssh-config --host {host_alias} > {ssh_config_var}',
        f'\trsync -avH -e "ssh -F {ssh_config_var}" --exclude .git --exclude .vagrant --exclude results --exclude paper/bin ./ {host_alias}:$(REMOTE_DIR)/',
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


def main() -> int:
    """Print the generated solution rules fragment to stdout."""
    profile_dir = "$(SOLUTION_DIR)"
    raw_targets = [f"{profile_dir}/consumer_capture.pcap", *node_pcap_paths(profile_dir)]
    lines = [
        "# Auto-generated file. Do not edit manually.",
        "# Source: scripts/makefile-solution.py",
        "",
        "# Solution experiment",
        f"{' '.join(raw_targets)} &: $(APP_SRCS) $(SOLUTION_SRCS) $(EXPERIMENT_TOOL_SRCS) $(SOLUTION_SSH_CONFIG) | results/solution $(SOLUTION_DIR)/pcap_nodes",
        *emit_workflow_recipe(
            vagrant_dir="experiment/solution",
            host_alias="solution",
            ssh_config_var="$(SOLUTION_SSH_CONFIG)",
            box_env_name="ACTUAL_SOLUTION_BOX_PATH",
            box_path="box/solution/solution.$(PROVIDER).box",
            experiment_subdir="experiment/solution",
            local_results_dir=profile_dir,
            remote_make_command="make all",
        ),
        "",
        "$(CSV_SOLUTION): $(CONSUMER_PCAP_SOLUTION)",
        '\ttshark -r "$<" -T fields -e frame.time_epoch -e frame.len -e ndn.type -e ndn.name -E separator=, -E header=y -E quote=d > "$@"',
        "",
        "$(OVERHEAD_CSV_SOLUTION): $(SOLUTION_NODE_PCAPS) $(OVERHEAD_EXTRACT_SCRIPT)",
        '\t$(PYTHON) $(OVERHEAD_EXTRACT_SCRIPT) --pcap-dir "$(SOLUTION_DIR)/pcap_nodes" --output "$@"',
        "",
        "$(SOLUTION_DISRUPTION_PDF): $(CSV_SOLUTION) $(PLOT_LATENCY_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_LATENCY_SCRIPT) --input "$(CSV_SOLUTION)" --plot-output "$@" --handoff-times "120, 240"',
        "",
        "$(SOLUTION_DIR)/disruption_metrics.txt: $(CSV_SOLUTION) $(PLOT_LATENCY_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_LATENCY_SCRIPT) --input "$(CSV_SOLUTION)" --metrics-output "$@" --handoff-times "120, 240"',
        "",
        "$(SOLUTION_LOSS_PDF): $(CSV_SOLUTION) $(PLOT_LOSS_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_LOSS_SCRIPT) --input "$(CSV_SOLUTION)" --plot-output "$@" --handoff-times "120, 240"',
        "",
        "$(SOLUTION_DIR)/loss_ratio.txt: $(CSV_SOLUTION) $(PLOT_LOSS_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_LOSS_SCRIPT) --input "$(CSV_SOLUTION)" --metrics-output "$@" --handoff-times "120, 240"',
        "",
        "$(SOLUTION_THROUGHPUT_PDF): $(CSV_SOLUTION) $(PLOT_THROUGHPUT_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_THROUGHPUT_SCRIPT) --input "$(CSV_SOLUTION)" --plot-output "$@" --handoff-times "120, 240"',
        "",
        "$(SOLUTION_DIR)/throughput_metrics.txt: $(CSV_SOLUTION) $(PLOT_THROUGHPUT_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_THROUGHPUT_SCRIPT) --input "$(CSV_SOLUTION)" --metrics-output "$@" --handoff-times "120, 240"',
        "",
        "$(SOLUTION_OVERHEAD_TIMESERIES_PDF): $(OVERHEAD_CSV_SOLUTION) $(MAIN_OVERHEAD_LIMITS_TXT) $(PLOT_OVERHEAD_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_OVERHEAD_SCRIPT) --input "$(OVERHEAD_CSV_SOLUTION)" --timeseries-output "$@" --handoff-times "120, 240" --limits-file "$(MAIN_OVERHEAD_LIMITS_TXT)"',
        "",
        "$(SOLUTION_OVERHEAD_SUMMARY_PDF): $(OVERHEAD_CSV_SOLUTION) $(MAIN_OVERHEAD_LIMITS_TXT) $(PLOT_OVERHEAD_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_OVERHEAD_SCRIPT) --input "$(OVERHEAD_CSV_SOLUTION)" --summary-output "$@" --handoff-times "120, 240" --limits-file "$(MAIN_OVERHEAD_LIMITS_TXT)"',
        "",
        "$(SOLUTION_DIR)/overhead_total.txt: $(OVERHEAD_CSV_SOLUTION) $(PLOT_OVERHEAD_SCRIPT) | $(VENV_DIR)",
        '\t$(PYTHON) $(PLOT_OVERHEAD_SCRIPT) --input "$(OVERHEAD_CSV_SOLUTION)" --metrics-output "$@" --handoff-times "120, 240"',
        "",
        "$(SOLUTION_DISRUPTION_FIGURE): $(SOLUTION_DISRUPTION_PDF) | paper/figures",
        '\tcp "$(SOLUTION_DISRUPTION_PDF)" "$@"',
        "",
        "$(SOLUTION_LOSS_FIGURE): $(SOLUTION_LOSS_PDF) | paper/figures",
        '\tcp "$(SOLUTION_LOSS_PDF)" "$@"',
        "",
        "$(SOLUTION_OVERHEAD_TIMESERIES_FIGURE): $(SOLUTION_OVERHEAD_TIMESERIES_PDF) | paper/figures",
        '\tcp "$(SOLUTION_OVERHEAD_TIMESERIES_PDF)" "$@"',
        "",
        "$(SOLUTION_OVERHEAD_SUMMARY_FIGURE): $(SOLUTION_OVERHEAD_SUMMARY_PDF) | paper/figures",
        '\tcp "$(SOLUTION_OVERHEAD_SUMMARY_PDF)" "$@"',
        "",
        "$(SOLUTION_THROUGHPUT_FIGURE): $(SOLUTION_THROUGHPUT_PDF) | paper/figures",
        '\tcp "$(SOLUTION_THROUGHPUT_PDF)" "$@"',
        "",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
