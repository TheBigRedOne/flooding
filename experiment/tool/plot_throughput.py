import argparse
import csv
import math
import os
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, ScalarFormatter


APP_PREFIX = "/example/LiveStream"

# ---------------------------------------------------------------------------
# TUNING: Figure canvas size (physical export size before LaTeX scaling).
# - Increase width/height to provide more drawing space.
# - Decrease width/height for tighter figures.
# ---------------------------------------------------------------------------
CM_TO_INCH = 1.0 / 2.54
PAPER_FIGURE_WIDTH_CM = 8.0
PAPER_FIGURE_HEIGHT_CM = 6.0

# ---------------------------------------------------------------------------
# TUNING: Text and style sizes used inside the figure.
# These values control labels/ticks/title/legend only, not the PDF canvas size.
# ---------------------------------------------------------------------------
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 8
LEGEND_SIZE = 8
FIGURE_TITLE_SIZE = 8

# ---------------------------------------------------------------------------
# TUNING: Visual element geometry.
# ---------------------------------------------------------------------------
THROUGHPUT_LINE_WIDTH = 1.0
HANDOFF_SHADE_ALPHA = 0.2
Y_TICK_BINS = 5
X_TICK_BINS = 5
LEGEND_MAX_COLUMNS = 2
LEGEND_BASE_OFFSET = 1.01
LEGEND_EXTRA_ROW_OFFSET = 0.05
TITLE_VERTICAL_POSITION = 1.20
Y_AXIS_HEADROOM_RATIO = 0.08
Y_AXIS_HEADROOM_MIN = 1.0


def _paper_figure_size() -> Tuple[float, float]:
    """Return figure size in inches for single-column paper readability."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, PAPER_FIGURE_HEIGHT_CM * CM_TO_INCH


def _configure_paper_style() -> None:
    """Apply plot style with larger labels for printed paper figures."""
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({
        "font.size": FONT_SIZE,
        "axes.labelsize": AXIS_LABEL_SIZE,
        "axes.titlesize": AXIS_TITLE_SIZE,
        "xtick.labelsize": TICK_LABEL_SIZE,
        "ytick.labelsize": TICK_LABEL_SIZE,
        "legend.fontsize": LEGEND_SIZE,
        "figure.titlesize": FIGURE_TITLE_SIZE,
    })
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _resolve_output_paths(
    output_dir: str | None,
    plot_output: str | None,
    metrics_output: str | None,
) -> Tuple[str | None, str | None]:
    """Resolve explicit output paths for the throughput figure and metrics file."""
    resolved_plot = plot_output
    resolved_metrics = metrics_output
    if output_dir:
        resolved_plot = resolved_plot or os.path.join(output_dir, "throughput_timeseries.pdf")
        resolved_metrics = resolved_metrics or os.path.join(output_dir, "throughput_metrics.txt")
    if resolved_plot is None and resolved_metrics is None:
        raise ValueError("At least one throughput output path must be specified.")
    return resolved_plot, resolved_metrics


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _place_legend_above_axis(ax) -> None:
    """Place the legend above the axis and below the axis title."""
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    legend_columns = min(len(handles), LEGEND_MAX_COLUMNS)
    legend_rows = math.ceil(len(handles) / legend_columns)
    vertical_offset = LEGEND_BASE_OFFSET + LEGEND_EXTRA_ROW_OFFSET * (legend_rows - 1)
    ax.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, vertical_offset),
        ncol=legend_columns,
        frameon=False,
        borderaxespad=0.0,
        columnspacing=0.8,
        handlelength=1.5,
        handletextpad=0.5,
    )


def _set_axis_title(ax, title: str) -> None:
    """Place the axis title above the legend region."""
    ax.set_title(title, y=TITLE_VERTICAL_POSITION, pad=0.0)


def _set_nonnegative_ylim_with_headroom(ax, values: List[int]) -> None:
    """Set a non-negative y-axis range with top headroom for plotted values."""
    max_value = max(values) if values else 0
    headroom = max(Y_AXIS_HEADROOM_MIN, max_value * Y_AXIS_HEADROOM_RATIO)
    ax.set_ylim(0, max(max_value + headroom, Y_AXIS_HEADROOM_MIN))


def _load_packets(csv_path: str) -> List[Tuple[float, int]]:
    """Load packet (time, length) tuples under the application prefix."""
    with open(csv_path, "r", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {"frame.time_epoch", "frame.len"}
        if not required.issubset(reader.fieldnames or set()):
            raise ValueError("Missing frame.time_epoch or frame.len; cannot compute throughput.")

        packets: List[Tuple[float, int]] = []
        for row in reader:
            name = (row.get("ndn.name") or "").strip()
            if not name:
                continue
            if name.startswith("/localhost/") or name.startswith("/localhop/ndn/nlsr/"):
                continue
            if not name.startswith(APP_PREFIX):
                continue
            try:
                time_val = float(row["frame.time_epoch"])
                length_val = int(row["frame.len"])
            except (ValueError, KeyError):
                continue
            packets.append((time_val, length_val))

    if not packets:
        raise ValueError("No valid rows available; throughput cannot be plotted.")

    return packets


def _aggregate_per_second(packets: Iterable[Tuple[float, int]]) -> Dict[int, int]:
    """Accumulate bytes per whole-second timestamp."""
    throughput: Dict[int, int] = defaultdict(int)
    for time_val, length_val in packets:
        second = int(time_val)
        throughput[second] += length_val
    return throughput


def _fill_missing_seconds(per_second: Dict[int, int]) -> Tuple[List[int], List[int]]:
    """Expand to continuous seconds, filling gaps with zero."""
    seconds = sorted(per_second.keys())
    if not seconds:
        return [], []
    full_seconds: List[int] = list(range(seconds[0], seconds[-1] + 1))
    values: List[int] = [per_second.get(sec, 0) for sec in full_seconds]
    return full_seconds, values


def _percentile(values: List[int], percentile: float) -> float:
    """Compute percentile with linear interpolation."""
    if not values:
        return 0.0
    if percentile <= 0:
        return float(min(values))
    if percentile >= 100:
        return float(max(values))

    sorted_vals = sorted(values)
    rank = (percentile / 100) * (len(sorted_vals) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_vals) - 1)
    fraction = rank - lower
    return sorted_vals[lower] + (sorted_vals[upper] - sorted_vals[lower]) * fraction


def _write_metrics(metrics_output: str | None, values: List[int], seconds: List[int]) -> None:
    """Write throughput metrics to the requested text output."""
    if metrics_output is None:
        return
    if not values or not seconds:
        avg = peak = p95 = total_bytes = 0
        duration = 0
    else:
        total_bytes = sum(values)
        duration = max(seconds[-1] - seconds[0] + 1, 1)
        avg = total_bytes / duration
        peak = max(values)
        p95 = _percentile(values, 95)

    _ensure_parent_dir(metrics_output)
    with open(metrics_output, "w", encoding="utf-8") as metrics_file:
        metrics_file.write(f"Average: {avg:.2f} bytes/s\n")
        metrics_file.write(f"Peak: {peak:.2f} bytes/s\n")
        metrics_file.write(f"P95: {p95:.2f} bytes/s\n")
        metrics_file.write(f"TotalBytes: {int(total_bytes)}\n")
        metrics_file.write(f"Duration: {duration:.2f} s\n")


def _safe_empty_outputs(plot_output: str | None, metrics_output: str | None) -> None:
    """Create empty outputs when input data is unusable."""
    _write_metrics(metrics_output, [], [])
    if plot_output is not None:
        _ensure_parent_dir(plot_output)
        _configure_paper_style()
        fig, _ = plt.subplots(figsize=_paper_figure_size())
        fig.savefig(plot_output)
        plt.close(fig)


def _write_plot(
    plot_output: str | None,
    rel_times: List[int],
    values: List[int],
    handoff_times: str | None,
    window: int,
) -> None:
    """Write the throughput time-series figure to the requested PDF output."""
    if plot_output is None:
        return
    _ensure_parent_dir(plot_output)
    _configure_paper_style()
    fig, ax = plt.subplots(figsize=_paper_figure_size())
    ax.plot(
        rel_times,
        values,
        color="steelblue",
        label="Bytes per second",
        linewidth=THROUGHPUT_LINE_WIDTH,
    )

    if handoff_times:
        handoffs = [float(t.strip()) for t in handoff_times.split(",") if t.strip()]
        for idx, handoff in enumerate(handoffs):
            start = handoff
            end = handoff + window
            label = "Handoff Window" if idx == 0 else None
            ax.axvspan(start, end, color="orange", alpha=HANDOFF_SHADE_ALPHA, label=label)

    ax.set_xlabel("Time (seconds)")
    ax.set_ylabel("Throughput (bytes/s)")
    _set_axis_title(ax, "Throughput Over Time")
    _place_legend_above_axis(ax)
    ax.grid(True)
    ax.yaxis.set_major_formatter(ScalarFormatter(useMathText=False))
    ax.ticklabel_format(style="plain", axis="y")
    _set_nonnegative_ylim_with_headroom(ax, values)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=Y_TICK_BINS))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=X_TICK_BINS, integer=True))
    ax.get_xaxis().get_major_formatter().set_useOffset(False)

    fig.tight_layout()
    fig.savefig(plot_output, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot throughput from tshark CSV.")
    parser.add_argument("--input", required=True, help="Path to tshark CSV.")
    parser.add_argument("--output-dir", help="Legacy directory used to derive default output files.")
    parser.add_argument("--plot-output", help="Path to the throughput PDF output.")
    parser.add_argument("--metrics-output", help="Path to the throughput metrics text output.")
    parser.add_argument("--handoff-times", help="Comma-separated handoff times in seconds (relative).")
    parser.add_argument("--window", type=int, default=10, help="Shaded window length after each handoff (seconds).")
    args = parser.parse_args()

    plot_output, metrics_output = _resolve_output_paths(
        args.output_dir,
        args.plot_output,
        args.metrics_output,
    )

    if not os.path.exists(args.input):
        _safe_empty_outputs(plot_output, metrics_output)
        return

    try:
        packets = _load_packets(args.input)
    except Exception:
        _safe_empty_outputs(plot_output, metrics_output)
        return

    per_second = _aggregate_per_second(packets)
    if not per_second:
        _safe_empty_outputs(plot_output, metrics_output)
        return

    full_seconds, values = _fill_missing_seconds(per_second)
    if not full_seconds:
        _safe_empty_outputs(plot_output, metrics_output)
        return

    start_second = full_seconds[0]
    rel_times = [sec - start_second for sec in full_seconds]

    _write_metrics(metrics_output, values, full_seconds)
    _write_plot(plot_output, rel_times, values, args.handoff_times, args.window)


if __name__ == "__main__":
    main()
