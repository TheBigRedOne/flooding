#!/usr/bin/env python3
"""Generate explicit host-side GNU Make rules for the solution experiment.

Purpose:
    Emit the solution experiment rules included by the top-level Makefile.
    The generated rules keep only grouped target and dependency variables.

Interface:
    python3 scripts/makefile-solution.py > Makefile.solution
"""

from __future__ import annotations


NODES = (
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


def node_pcap_paths() -> list[str]:
    """Return the solution per-node pcap targets."""
    return [f"results/solution/pcap_nodes/{node}.pcap" for node in NODES]


def emit_list(name: str, values: list[str], indent: int) -> list[str]:
    """Emit one GNU Make variable assignment containing a grouped file list."""
    padding = " " * indent
    lines = [f"{name} = {values[0]} \\"]
    for value in values[1:-1]:
        lines.append(f"{padding}{value} \\")
    lines.append(f"{padding}{values[-1]}")
    return lines


def main() -> int:
    """Print the generated solution rules fragment to stdout."""
    node_pcaps = node_pcap_paths()
    solution_results = ["results/solution/consumer_capture.pcap", *node_pcaps]

    lines = [
        "# Auto-generated file. Do not edit manually.",
        "# Source: scripts/makefile-solution.py",
        "",
        "# Solution experiment",
        *emit_list("SOLUTION_RESULTS", solution_results, 19),
        "",
        *emit_list("SOLUTION_NODE_PCAPS", node_pcaps, 22),
        "",
        "SOLUTION_INPUTS = $(APP_SRCS) $(SOLUTION_SRCS) experiment/tool/exp.py",
        "",
        "$(SOLUTION_RESULTS) &: scripts/run-in-vm.sh box/solution/solution.$(PROVIDER).box $(SOLUTION_INPUTS)",
        "\tsh $^ $@",
        "",
        "results/solution/consumer_capture.csv: results/solution/consumer_capture.pcap experiment/tool/ndn.lua",
        '\ttshark -X lua_script:experiment/tool/ndn.lua -r "$<" -T fields -e frame.time_epoch -e frame.len -e ndn.type -e ndn.name -E separator=, -E header=y -E quote=d > "$@"',
        "",
        "results/solution/network_overhead.csv: experiment/tool/extract_overhead_csv.py $(SOLUTION_NODE_PCAPS)",
        "\tpython3 $^ $@",
        "",
        "results/solution/disruption_times.pdf: experiment/tool/plot_latency.py results/solution/disruption_metrics.txt",
        "\tpython3 $^ $@",
        "",
        "results/solution/disruption_metrics.txt: experiment/tool/compute_latency_metrics.py results/solution/consumer_capture.csv",
        "\tpython3 $^ $@",
        "",
        "results/solution/loss_comparison.pdf: experiment/tool/plot_loss.py results/solution/loss_ratio.txt",
        "\tpython3 $^ $@",
        "",
        "results/solution/loss_ratio.txt: experiment/tool/compute_loss_metrics.py results/solution/consumer_capture.csv",
        "\tpython3 $^ $@",
        "",
        "results/solution/throughput_timeseries.pdf: experiment/tool/plot_throughput.py results/solution/consumer_capture.csv",
        "\tpython3 $^ $@",
        "",
        "results/solution/throughput_metrics.txt: experiment/tool/compute_throughput_metrics.py results/solution/consumer_capture.csv",
        "\tpython3 $^ $@",
        "",
        "results/solution/overhead_timeseries.pdf: experiment/tool/plot_overhead.py results/solution/network_overhead.csv results/main_overhead_limits.txt",
        "\tpython3 $^ $@",
        "",
        "results/solution/overhead_summary.pdf: experiment/tool/plot_overhead.py results/solution/network_overhead.csv results/main_overhead_limits.txt",
        "\tpython3 $^ $@",
        "",
        "results/solution/overhead_total.txt: experiment/tool/compute_overhead_metrics.py results/solution/network_overhead.csv | experiment/tool/plot_overhead.py",
        "\tpython3 $^ $@",
        "",
        "paper/figures/solution_disruption.pdf: results/solution/disruption_times.pdf | paper/figures",
        '\tcp results/solution/disruption_times.pdf "$@"',
        "",
        "paper/figures/solution_loss.pdf: results/solution/loss_comparison.pdf | paper/figures",
        '\tcp results/solution/loss_comparison.pdf "$@"',
        "",
        "paper/figures/solution_overhead_timeseries.pdf: results/solution/overhead_timeseries.pdf | paper/figures",
        '\tcp results/solution/overhead_timeseries.pdf "$@"',
        "",
        "paper/figures/solution_overhead_summary.pdf: results/solution/overhead_summary.pdf | paper/figures",
        '\tcp results/solution/overhead_summary.pdf "$@"',
        "",
        "paper/figures/solution_throughput.pdf: results/solution/throughput_timeseries.pdf | paper/figures",
        '\tcp results/solution/throughput_timeseries.pdf "$@"',
        "",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
