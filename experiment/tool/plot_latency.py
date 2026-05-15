import argparse
import os
from typing import List

import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# TUNING: Figure canvas size (physical export size before LaTeX scaling).
# ---------------------------------------------------------------------------
CM_TO_INCH = 1.0 / 2.54
PAPER_FIGURE_WIDTH_CM = 8.0
PAPER_FIGURE_HEIGHT_CM = 6.0

# ---------------------------------------------------------------------------
# TUNING: Text sizes inside the plot.
# ---------------------------------------------------------------------------
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 8
FIGURE_TITLE_SIZE = 8

# ---------------------------------------------------------------------------
# TUNING: Bar chart appearance.
# ---------------------------------------------------------------------------
BAR_COLOR = 'skyblue'


def _paper_figure_size():
    """Return figure size in inches for printed two-column papers."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style():
    """Apply style with larger labels for paper figures."""
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams.update({
        "font.size": FONT_SIZE,
        "axes.labelsize": AXIS_LABEL_SIZE,
        "axes.titlesize": AXIS_TITLE_SIZE,
        "xtick.labelsize": TICK_LABEL_SIZE,
        "ytick.labelsize": TICK_LABEL_SIZE,
        "figure.titlesize": FIGURE_TITLE_SIZE,
    })
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load_metrics(metrics_input: str) -> List[float]:
    """Read service-disruption values from the metrics text file."""
    disruption_times: List[float] = []
    with open(metrics_input, "r", encoding="utf-8") as metrics_file:
        for line in metrics_file:
            if "Disruption Time:" not in line:
                continue
            raw_value = line.split("Disruption Time:", 1)[1].strip().split()[0]
            disruption_times.append(float(raw_value))
    return disruption_times


def _write_plot(plot_output: str | None, disruption_times: List[float]) -> None:
    """Write the disruption bar chart to the requested PDF output."""
    if plot_output is None:
        return
    _ensure_parent_dir(plot_output)
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    handoff_labels = [str(i + 1) for i in range(len(disruption_times))]
    ax.bar(handoff_labels, disruption_times, color=BAR_COLOR)
    if disruption_times:
        mean_value = sum(disruption_times) / len(disruption_times)
        ax.axhline(mean_value, color='gray', linestyle='--', linewidth=1.0, label=f'mean={mean_value:.0f} ms')
        ax.legend(loc='upper right', frameon=False)
    ax.set_xlabel('Handoff index')
    ax.set_ylabel('Service Disruption Time (ms)')
    ax.set_title('Per-Handoff Service Disruption')
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    fig.tight_layout()
    plt.savefig(plot_output)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Plot service-disruption metrics.")
    parser.add_argument("metrics_input", help="Input disruption metrics text file.")
    parser.add_argument("plot_output", help="Output disruption PDF path.")
    args = parser.parse_args()

    _configure_paper_style()
    disruption_times = _load_metrics(args.metrics_input)
    if not disruption_times:
        _ensure_parent_dir(args.plot_output)
        open(args.plot_output, "w").close()
        return

    _write_plot(args.plot_output, disruption_times)
    
    print("Generated service disruption outputs")

if __name__ == '__main__':
    main()
