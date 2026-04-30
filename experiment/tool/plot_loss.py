import argparse
import os
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
# TUNING: Bar chart and annotation appearance.
# ---------------------------------------------------------------------------
HANDOFF_BAR_COLOR = 'orangered'
STEADY_BAR_COLOR = 'deepskyblue'
VALUE_LABEL_OFFSET_MIN = 0.02
VALUE_LABEL_OFFSET_RATIO = 0.025
LOSS_Y_TOP_PADDING = 0.08
TITLE_PAD_POINTS = 4.0


def _paper_figure_size():
    """Return figure size in inches for single-column paper figures."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style():
    """Apply style with larger labels for paper readability."""
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


def _load_metrics(metrics_input: str) -> tuple[list[float], float]:
    """Read unmet-Interest ratios and deadline from a metrics text file."""
    values: dict[str, float] = {
        "Handoff Window Ratio": 1.0,
        "Steady State Ratio": 1.0,
        "Deadline Seconds": 6.0,
    }
    with open(metrics_input, "r", encoding="utf-8") as metrics_file:
        for line in metrics_file:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key in values:
                values[key] = float(value.strip().split()[0])
    return [values["Handoff Window Ratio"], values["Steady State Ratio"]], values["Deadline Seconds"]


def _write_plot(plot_output: str | None, ratios: list[float], deadline: float) -> None:
    """Write the unmet-interest comparison figure to the requested PDF output."""
    if plot_output is None:
        return
    _ensure_parent_dir(plot_output)
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    labels = ['During\nHandoffs', 'Steady\nState']
    max_ratio = max(ratios) if ratios else 0.0
    label_offset = max(VALUE_LABEL_OFFSET_MIN, VALUE_LABEL_OFFSET_RATIO * max_ratio)
    ax.bar(labels, ratios, color=[HANDOFF_BAR_COLOR, STEADY_BAR_COLOR])
    ax.set_ylabel('Unmet-Interest Ratio')
    ax.set_title(
        f'Comparison of Unmet-Interest Ratio (deadline={deadline:.1f}s)',
        pad=TITLE_PAD_POINTS,
    )
    ax.set_ylim(0, max(1.0 + LOSS_Y_TOP_PADDING, max_ratio + label_offset + LOSS_Y_TOP_PADDING))
    ax.grid(axis='y', linestyle='--', alpha=0.7)

    for i, value in enumerate(ratios):
        ax.text(i, value + label_offset, f"{value:.3f}", ha='center', va='bottom')

    fig.tight_layout()
    fig.savefig(plot_output, bbox_inches='tight')
    plt.close(fig)

def main():
    parser = argparse.ArgumentParser(description="Plot unmet-Interest metrics.")
    parser.add_argument("metrics_input", help="Input unmet-Interest metrics text file.")
    parser.add_argument("plot_output", help="Output loss comparison PDF path.")
    args = parser.parse_args()

    _configure_paper_style()
    ratios, deadline = _load_metrics(args.metrics_input)
    _write_plot(args.plot_output, ratios, deadline)

if __name__ == '__main__':
    main()
