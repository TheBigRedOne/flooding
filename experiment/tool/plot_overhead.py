import argparse
import os
from dataclasses import dataclass
from typing import List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

# ---------------------------------------------------------------------------
# TUNING: Figure canvas size (physical export size before LaTeX scaling).
# ---------------------------------------------------------------------------
CM_TO_INCH = 1.0 / 2.54
PAPER_FIGURE_WIDTH_CM = 8.0
TIMESERIES_FIGURE_HEIGHT_CM = 6.5
SUMMARY_FIGURE_HEIGHT_CM = 7.0

# ---------------------------------------------------------------------------
# TUNING: Text sizes inside the plot.
# ---------------------------------------------------------------------------
FONT_SIZE = 8
AXIS_LABEL_SIZE = 8
AXIS_TITLE_SIZE = 8
TICK_LABEL_SIZE = 8
LEGEND_SIZE = 8
FIGURE_TITLE_SIZE = 8

# ---------------------------------------------------------------------------
# TUNING: Time-series visual style.
# ---------------------------------------------------------------------------
OVERHEAD_LINE_WIDTH = 1.0
HANDOFF_SHADE_ALPHA = 0.18
X_TICK_BINS = 5
SUMMARY_BAR_WIDTH = 0.32
LEGEND_MAX_COLUMNS = 2
Y_AXIS_HEADROOM_RATIO = 0.10
Y_AXIS_HEADROOM_MIN = 1.0
FIGURE_LEFT_MARGIN = 0.16
FIGURE_RIGHT_MARGIN = 0.98
FIGURE_TOP_MARGIN = 0.96
TIMESERIES_FIGURE_BOTTOM_MARGIN = 0.18
SUMMARY_FIGURE_BOTTOM_MARGIN = 0.28
HEADER_GRID_VERTICAL_SPACING = 0.08
HEADER_HEIGHT_RATIO = 0.80
PLOT_HEIGHT_RATIO = 1.8
APP_TOTAL_COLOR = 'crimson'
FLOOD_COLOR = 'darkorange'
APP_OTHER_COLOR = 'steelblue'
CONTROL_COLOR = 'slateblue'
INTEREST_OTHER_COLOR = 'royalblue'
INTEREST_FLOOD_COLOR = 'darkorange'
DATA_OTHER_COLOR = 'seagreen'
DATA_FLOOD_COLOR = 'firebrick'
DEFAULT_RELAY_NODES = ['core', 'agg1', 'agg2', 'acc1', 'acc2', 'acc3', 'acc4', 'acc5', 'acc6']
LOCALHOST_PREFIX = '/localhost/'
OVERHEAD_TIMESERIES_FILENAME = 'overhead_timeseries.pdf'
OVERHEAD_SUMMARY_FILENAME = 'overhead_summary.pdf'
OVERHEAD_METRICS_FILENAME = 'overhead_total.txt'


@dataclass
class WindowSummary:
    label: str
    app_relay_packets: int
    app_relay_bytes: int
    interest_relay_bytes: int
    data_relay_bytes: int
    flood_packets: int
    flood_bytes: int
    interest_flood_bytes: int
    data_flood_bytes: int
    control_packets: int
    control_bytes: int
    delivered_packets: int
    delivered_bytes: int
    forwarding_cost_ratio: Optional[float]
    flood_share: Optional[float]


@dataclass
class OverheadAnalysis:
    relay_nodes: List[str]
    time_axis: List[int]
    interest_other_series: pd.Series
    interest_flood_series: pd.Series
    data_other_series: pd.Series
    data_flood_series: pd.Series
    control_series: pd.Series
    handoff_summaries: List[WindowSummary]
    full_run_summary: WindowSummary


def _paper_figure_size(height_cm: float):
    """Return figure size in inches for a single-column paper figure."""
    return PAPER_FIGURE_WIDTH_CM * CM_TO_INCH, height_cm * CM_TO_INCH


def _configure_paper_style():
    """Apply style with larger labels for paper readability."""
    plt.style.use('seaborn-v0_8-whitegrid')
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


def _populate_header_axis(header_ax, plot_ax, title: str) -> None:
    """Render a dedicated header band containing the subplot title and legend."""
    header_ax.set_axis_off()
    header_ax.text(
        0.5,
        0.98,
        title,
        ha='center',
        va='top',
        transform=header_ax.transAxes,
    )

    handles, labels = plot_ax.get_legend_handles_labels()
    if not handles:
        return

    header_ax.legend(
        handles,
        labels,
        loc='lower center',
        bbox_to_anchor=(0.5, 0.02),
        ncol=min(len(handles), LEGEND_MAX_COLUMNS),
        frameon=False,
        borderaxespad=0.0,
        columnspacing=0.8,
        handlelength=1.5,
        handletextpad=0.5,
    )


def _create_figure_with_header(height_cm: float, bottom_margin: float):
    """Create a figure with a dedicated header axis above the plot axis."""
    fig = plt.figure(figsize=_paper_figure_size(height_cm))
    grid = fig.add_gridspec(
        2,
        1,
        left=FIGURE_LEFT_MARGIN,
        right=FIGURE_RIGHT_MARGIN,
        top=FIGURE_TOP_MARGIN,
        bottom=bottom_margin,
        hspace=HEADER_GRID_VERTICAL_SPACING,
        height_ratios=[HEADER_HEIGHT_RATIO, PLOT_HEIGHT_RATIO],
    )
    header_ax = fig.add_subplot(grid[0])
    plot_ax = fig.add_subplot(grid[1])
    return fig, header_ax, plot_ax


def _save_empty_pdf(output_path: str, height_cm: float) -> None:
    """Write a valid empty PDF placeholder with the requested figure size."""
    fig = plt.figure(figsize=_paper_figure_size(height_cm))
    fig.savefig(output_path)
    plt.close(fig)


def _resolve_output_paths(
    output_dir: str | None,
    timeseries_output: str | None,
    summary_output: str | None,
    metrics_output: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve explicit output paths for the requested overhead artifacts."""
    resolved_timeseries = timeseries_output
    resolved_summary = summary_output
    resolved_metrics = metrics_output
    if output_dir:
        resolved_timeseries = resolved_timeseries or os.path.join(output_dir, OVERHEAD_TIMESERIES_FILENAME)
        resolved_summary = resolved_summary or os.path.join(output_dir, OVERHEAD_SUMMARY_FILENAME)
        resolved_metrics = resolved_metrics or os.path.join(output_dir, OVERHEAD_METRICS_FILENAME)
    if resolved_timeseries is None and resolved_summary is None and resolved_metrics is None:
        raise ValueError("At least one overhead output path must be specified.")
    return resolved_timeseries, resolved_summary, resolved_metrics


def _ensure_parent_dir(path: str) -> None:
    """Create the parent directory for one output path when needed."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load_limits_file(path: str) -> tuple[float, float]:
    """Read shared overhead y-axis limits from one text file."""
    with open(path, 'r', encoding='utf-8') as input_file:
        values = input_file.read().strip().split()
    if len(values) != 2:
        raise ValueError(f"Invalid overhead limits file: {path}")
    return float(values[0]), float(values[1])


def _compute_y_axis_upper_bound(values: List[float]) -> float:
    """Compute a non-negative y-axis upper bound with top headroom."""
    max_value = max(values) if values else 0.0
    headroom = max(Y_AXIS_HEADROOM_MIN, max_value * Y_AXIS_HEADROOM_RATIO)
    return max(max_value + headroom, Y_AXIS_HEADROOM_MIN)


def _set_nonnegative_ylim_with_headroom(ax, values: List[float], explicit_max: Optional[float] = None) -> None:
    """Set a non-negative y-axis range using either a shared limit or local headroom."""
    upper_bound = explicit_max if explicit_max is not None else _compute_y_axis_upper_bound(values)
    ax.set_ylim(0, upper_bound)


def _format_summary_tick_label(summary: WindowSummary) -> str:
    """Format the summary tick label with per-window forwarding metrics."""
    return (
        f"{summary.label}\n"
        f"FCR={_format_ratio(summary.forwarding_cost_ratio)}\n"
        f"Flood={_format_ratio(summary.flood_share, percent=True)}"
    )


def _compute_timeseries_y_max(analysis: OverheadAnalysis) -> float:
    """Compute the y-axis upper bound for the time-series overhead plot."""
    return _compute_y_axis_upper_bound([
        float(analysis.interest_other_series.max()),
        float(analysis.interest_flood_series.max()),
        float(analysis.data_other_series.max()),
        float(analysis.data_flood_series.max()),
        float(analysis.control_series.max()),
    ])


def _compute_summary_y_max(analysis: OverheadAnalysis) -> float:
    """Compute the y-axis upper bound for the summary overhead plot."""
    summary_items = analysis.handoff_summaries if analysis.handoff_summaries else [analysis.full_run_summary]
    interest_totals = [item.interest_relay_bytes for item in summary_items]
    data_totals = [item.data_relay_bytes for item in summary_items]
    control_totals = [item.control_bytes for item in summary_items]
    return _compute_y_axis_upper_bound([
        *interest_totals,
        *data_totals,
        *control_totals,
        1.0,
    ])


def _write_empty_outputs(
    timeseries_output: str | None,
    summary_output: str | None,
    metrics_output: str | None,
) -> None:
    """Create empty placeholder outputs for missing or unusable input data."""
    if timeseries_output is not None:
        _ensure_parent_dir(timeseries_output)
        _save_empty_pdf(timeseries_output, TIMESERIES_FIGURE_HEIGHT_CM)
    if summary_output is not None:
        _ensure_parent_dir(summary_output)
        _save_empty_pdf(summary_output, SUMMARY_FIGURE_HEIGHT_CM)
    if metrics_output is not None:
        _ensure_parent_dir(metrics_output)
        with open(metrics_output, 'w', encoding='utf-8') as output_file:
            output_file.write("No usable overhead data available.\n")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        'frame.time_epoch': 'time',
        'frame.len': 'length',
        'frame.number': 'frame_number',
        'ndn.type': 'type',
        'ndn.name': 'name',
        'ndn.flood_id': 'flood_id',
        'ndn.new_face_seq': 'new_face_seq',
        'ndn.lp.hoplimit': 'lp_hoplimit',
        'ndn.lp.mobility_flag': 'lp_mobility_flag',
        'ndn.hoplimit': 'hoplimit',
        'sll.pkttype': 'pkttype',
        'sll.ifindex': 'ifindex',
    })
    for column in [
        'node', 'frame_number', 'time', 'length', 'pkttype', 'ifindex', 'type', 'name',
        'flood_id', 'new_face_seq', 'lp_hoplimit', 'lp_mobility_flag', 'hoplimit',
    ]:
        if column not in df.columns:
            df[column] = pd.NA
    return df


def _parse_relay_nodes(raw: str) -> List[str]:
    if not raw.strip():
        return DEFAULT_RELAY_NODES
    return [node.strip() for node in raw.split(',') if node.strip()]


def _parse_handoff_times(raw: Optional[str]) -> List[float]:
    if not raw:
        return []
    return [float(token.strip()) for token in raw.split(',') if token.strip()]


def _series_has_text(series: pd.Series) -> pd.Series:
    return series.fillna('').astype(str).str.strip() != ''


def _is_nlsr_control_name(series: pd.Series) -> pd.Series:
    return series.astype(str).str.contains('/nlsr/', regex=False)


def _aggregate_bytes_per_second(df: pd.DataFrame, max_second: int) -> pd.Series:
    if df.empty:
        return pd.Series([0] * (max_second + 1), index=range(max_second + 1), dtype='int64')
    grouped = df.groupby('second')['length'].sum().astype('int64')
    return grouped.reindex(range(max_second + 1), fill_value=0)


def _format_ratio(value: Optional[float], *, percent: bool = False) -> str:
    if value is None:
        return 'n/a'
    return f"{value * 100:.1f}%" if percent else f"{value:.2f}"


def _summarize_window(
    label: str,
    start: Optional[float],
    end: Optional[float],
    relay_app_out: pd.DataFrame,
    relay_interest_out: pd.DataFrame,
    relay_data_out: pd.DataFrame,
    relay_flood_out: pd.DataFrame,
    relay_interest_flood_out: pd.DataFrame,
    relay_data_flood_out: pd.DataFrame,
    relay_control_out: pd.DataFrame,
    delivered_data_in: pd.DataFrame,
) -> WindowSummary:
    if start is None or end is None:
        app_df = relay_app_out
        interest_df = relay_interest_out
        data_df = relay_data_out
        flood_df = relay_flood_out
        interest_flood_df = relay_interest_flood_out
        data_flood_df = relay_data_flood_out
        control_df = relay_control_out
        delivered_df = delivered_data_in
    else:
        app_df = relay_app_out[(relay_app_out['relative_time'] >= start) & (relay_app_out['relative_time'] < end)]
        interest_df = relay_interest_out[
            (relay_interest_out['relative_time'] >= start) &
            (relay_interest_out['relative_time'] < end)
        ]
        data_df = relay_data_out[
            (relay_data_out['relative_time'] >= start) &
            (relay_data_out['relative_time'] < end)
        ]
        flood_df = relay_flood_out[(relay_flood_out['relative_time'] >= start) & (relay_flood_out['relative_time'] < end)]
        interest_flood_df = relay_interest_flood_out[
            (relay_interest_flood_out['relative_time'] >= start) &
            (relay_interest_flood_out['relative_time'] < end)
        ]
        data_flood_df = relay_data_flood_out[
            (relay_data_flood_out['relative_time'] >= start) &
            (relay_data_flood_out['relative_time'] < end)
        ]
        control_df = relay_control_out[
            (relay_control_out['relative_time'] >= start) &
            (relay_control_out['relative_time'] < end)
        ]
        delivered_df = delivered_data_in[
            (delivered_data_in['relative_time'] >= start) &
            (delivered_data_in['relative_time'] < end)
        ]

    app_relay_bytes = int(app_df['length'].sum()) if not app_df.empty else 0
    flood_bytes = int(flood_df['length'].sum()) if not flood_df.empty else 0
    delivered_bytes = int(delivered_df['length'].sum()) if not delivered_df.empty else 0

    forwarding_cost_ratio = None
    if delivered_bytes > 0:
        forwarding_cost_ratio = app_relay_bytes / delivered_bytes

    flood_share = None
    if app_relay_bytes > 0:
        flood_share = flood_bytes / app_relay_bytes

    return WindowSummary(
        label=label,
        app_relay_packets=len(app_df),
        app_relay_bytes=app_relay_bytes,
        interest_relay_bytes=int(interest_df['length'].sum()) if not interest_df.empty else 0,
        data_relay_bytes=int(data_df['length'].sum()) if not data_df.empty else 0,
        flood_packets=len(flood_df),
        flood_bytes=flood_bytes,
        interest_flood_bytes=int(interest_flood_df['length'].sum()) if not interest_flood_df.empty else 0,
        data_flood_bytes=int(data_flood_df['length'].sum()) if not data_flood_df.empty else 0,
        control_packets=len(control_df),
        control_bytes=int(control_df['length'].sum()) if not control_df.empty else 0,
        delivered_packets=len(delivered_df),
        delivered_bytes=delivered_bytes,
        forwarding_cost_ratio=forwarding_cost_ratio,
        flood_share=flood_share,
    )


def _load_analysis(
    input_path: str,
    prefix: str,
    relay_nodes_arg: str,
    consumer_node: str,
    handoff_times_arg: Optional[str],
    window: float,
) -> OverheadAnalysis:
    """Load the input CSV and derive reusable overhead analysis series and summaries."""
    try:
        df = pd.read_csv(input_path)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError) as exc:
        raise ValueError(f"Input file {input_path} is empty or not found.") from exc

    df = _normalize_columns(df)
    required_cols = {'node', 'time', 'length', 'type', 'name'}
    if not required_cols.issubset(set(df.columns)):
        missing = sorted(required_cols - set(df.columns))
        raise ValueError(f"Missing required columns {missing}.")

    df = df.dropna(subset=['time', 'length', 'type', 'name']).copy()
    df['time'] = pd.to_numeric(df['time'], errors='coerce')
    df['length'] = pd.to_numeric(df['length'], errors='coerce')
    df['pkttype'] = pd.to_numeric(df['pkttype'], errors='coerce')
    df['flood_id'] = pd.to_numeric(df['flood_id'], errors='coerce')
    df['new_face_seq'] = pd.to_numeric(df['new_face_seq'], errors='coerce')
    df['lp_hoplimit'] = pd.to_numeric(df['lp_hoplimit'], errors='coerce')
    df['hoplimit'] = pd.to_numeric(df['hoplimit'], errors='coerce')
    df = df.dropna(subset=['time', 'length'])
    df['type'] = df['type'].astype(str).str.lower()
    df['name'] = df['name'].astype(str)
    df['node'] = df['node'].astype(str)

    df['is_control'] = _is_nlsr_control_name(df['name'])
    df['is_localhost'] = df['name'].str.startswith(LOCALHOST_PREFIX)
    df['is_app'] = (
        df['name'].str.startswith(prefix) &
        ~df['is_control'] &
        ~df['is_localhost']
    )
    if not df['is_app'].any():
        raise ValueError("No app traffic found.")

    start_time = float(df.loc[df['is_app'], 'time'].min())
    df['relative_time'] = df['time'] - start_time
    df = df[df['relative_time'] >= 0].copy()
    if df.empty:
        raise ValueError("No packets remain after aligning to app start time.")

    has_direction = df['pkttype'].notna().any()
    if has_direction:
        df['is_outbound'] = df['pkttype'] == 4
        df['is_inbound'] = df['pkttype'] != 4
    else:
        df['is_outbound'] = True
        df['is_inbound'] = True

    df['is_app_interest'] = df['is_app'] & (df['type'] == 'interest')
    df['is_app_data'] = df['is_app'] & (df['type'] == 'data')
    df['has_lp_mobility_flag'] = _series_has_text(df['lp_mobility_flag'])
    df['has_lp_hoplimit'] = df['lp_hoplimit'].notna()
    df['has_interest_hoplimit'] = df['hoplimit'].notna()
    df['is_interest_flood'] = df['is_app_interest'] & df['has_interest_hoplimit']
    df['is_data_flood'] = df['is_app_data'] & (df['has_lp_hoplimit'] | df['has_lp_mobility_flag'])
    df['is_explicit_flood'] = df['is_interest_flood'] | df['is_data_flood']
    df['second'] = df['relative_time'].astype(int)

    relay_nodes = _parse_relay_nodes(relay_nodes_arg)
    relay_mask = df['node'].isin(relay_nodes)

    relay_app_out = df[relay_mask & df['is_outbound'] & df['is_app']].copy()
    relay_interest_out = df[relay_mask & df['is_outbound'] & df['is_app_interest']].copy()
    relay_data_out = df[relay_mask & df['is_outbound'] & df['is_app_data']].copy()
    relay_flood_out = df[relay_mask & df['is_outbound'] & df['is_explicit_flood']].copy()
    relay_interest_flood_out = df[relay_mask & df['is_outbound'] & df['is_interest_flood']].copy()
    relay_data_flood_out = df[relay_mask & df['is_outbound'] & df['is_data_flood']].copy()
    relay_control_out = df[relay_mask & df['is_outbound'] & df['is_control']].copy()
    delivered_data_in = df[
        (df['node'] == consumer_node) &
        df['is_inbound'] &
        df['is_app_data']
    ].copy()

    if relay_app_out.empty:
        raise ValueError("No relay outbound app traffic after filtering.")

    max_second = int(max(
        relay_app_out['second'].max() if not relay_app_out.empty else 0,
        relay_control_out['second'].max() if not relay_control_out.empty else 0,
        delivered_data_in['second'].max() if not delivered_data_in.empty else 0,
    ))
    max_second = max(max_second, 0)

    relay_interest_series = _aggregate_bytes_per_second(relay_interest_out, max_second)
    relay_data_series = _aggregate_bytes_per_second(relay_data_out, max_second)
    relay_interest_flood_series = _aggregate_bytes_per_second(relay_interest_flood_out, max_second)
    relay_data_flood_series = _aggregate_bytes_per_second(relay_data_flood_out, max_second)
    relay_control_series = _aggregate_bytes_per_second(relay_control_out, max_second)
    relay_interest_other_series = (relay_interest_series - relay_interest_flood_series).clip(lower=0)
    relay_data_other_series = (relay_data_series - relay_data_flood_series).clip(lower=0)
    time_axis = list(range(max_second + 1))

    handoff_times = _parse_handoff_times(handoff_times_arg)
    handoff_summaries = [
        _summarize_window(
            f'Handoff {index + 1}',
            handoff_time,
            handoff_time + window,
            relay_app_out,
            relay_interest_out,
            relay_data_out,
            relay_flood_out,
            relay_interest_flood_out,
            relay_data_flood_out,
            relay_control_out,
            delivered_data_in,
        )
        for index, handoff_time in enumerate(handoff_times)
    ]
    full_run_summary = _summarize_window(
        'Full Run',
        None,
        None,
        relay_app_out,
        relay_interest_out,
        relay_data_out,
        relay_flood_out,
        relay_interest_flood_out,
        relay_data_flood_out,
        relay_control_out,
        delivered_data_in,
    )

    return OverheadAnalysis(
        relay_nodes=relay_nodes,
        time_axis=time_axis,
        interest_other_series=relay_interest_other_series,
        interest_flood_series=relay_interest_flood_series,
        data_other_series=relay_data_other_series,
        data_flood_series=relay_data_flood_series,
        control_series=relay_control_series,
        handoff_summaries=handoff_summaries,
        full_run_summary=full_run_summary,
    )


def _write_summary_file(
    output_path: str,
    relay_nodes: List[str],
    consumer_node: str,
    window_seconds: float,
    handoff_summaries: List[WindowSummary],
    full_run_summary: WindowSummary,
) -> None:
    with open(output_path, 'w', encoding='utf-8') as output_file:
        output_file.write(f"Relay Nodes: {','.join(relay_nodes)}\n")
        output_file.write(f"Consumer Node: {consumer_node}\n")
        output_file.write(f"Handoff Window Seconds: {window_seconds:.2f}\n")
        output_file.write("\n")

        for summary in [*handoff_summaries, full_run_summary]:
            output_file.write(f"[{summary.label}]\n")
            output_file.write(f"App Relay Packets: {summary.app_relay_packets}\n")
            output_file.write(f"App Relay Bytes: {summary.app_relay_bytes}\n")
            output_file.write(f"Interest Relay Bytes: {summary.interest_relay_bytes}\n")
            output_file.write(f"Data Relay Bytes: {summary.data_relay_bytes}\n")
            output_file.write(f"Explicit Flood Packets: {summary.flood_packets}\n")
            output_file.write(f"Explicit Flood Bytes: {summary.flood_bytes}\n")
            output_file.write(f"Interest Flood Bytes: {summary.interest_flood_bytes}\n")
            output_file.write(f"Data Flood Bytes: {summary.data_flood_bytes}\n")
            output_file.write(f"Other Interest Forwarding Bytes: {summary.interest_relay_bytes - summary.interest_flood_bytes}\n")
            output_file.write(f"Other Data Forwarding Bytes: {summary.data_relay_bytes - summary.data_flood_bytes}\n")
            output_file.write(f"Other App Forwarding Bytes: {summary.app_relay_bytes - summary.flood_bytes}\n")
            output_file.write(f"NLSR Control Packets: {summary.control_packets}\n")
            output_file.write(f"NLSR Control Bytes: {summary.control_bytes}\n")
            output_file.write(f"Delivered Data Packets: {summary.delivered_packets}\n")
            output_file.write(f"Delivered Data Bytes: {summary.delivered_bytes}\n")
            output_file.write(
                f"Forwarding Cost Ratio: "
                f"{_format_ratio(summary.forwarding_cost_ratio)}\n"
            )
            output_file.write(f"Flood Share: {_format_ratio(summary.flood_share, percent=True)}\n")
            output_file.write("\n")


def _write_timeseries_plot(
    output_path: str | None,
    analysis: OverheadAnalysis,
    handoff_times_arg: str | None,
    window: float,
    explicit_max: Optional[float],
) -> None:
    """Write the overhead time-series figure to the requested PDF output."""
    if output_path is None:
        return
    _ensure_parent_dir(output_path)
    timeseries_fig, ax_timeseries_header, ax_timeseries = _create_figure_with_header(
        TIMESERIES_FIGURE_HEIGHT_CM,
        TIMESERIES_FIGURE_BOTTOM_MARGIN,
    )

    ax_timeseries.plot(
        analysis.time_axis,
        analysis.interest_other_series.tolist(),
        label='Non-flood Interest Relay',
        color=INTEREST_OTHER_COLOR,
        linewidth=OVERHEAD_LINE_WIDTH,
    )
    ax_timeseries.plot(
        analysis.time_axis,
        analysis.interest_flood_series.tolist(),
        label='Flooded Interest Relay',
        color=INTEREST_FLOOD_COLOR,
        linewidth=OVERHEAD_LINE_WIDTH,
        linestyle='--',
    )
    ax_timeseries.plot(
        analysis.time_axis,
        analysis.data_other_series.tolist(),
        label='Non-flood Data Relay',
        color=DATA_OTHER_COLOR,
        linewidth=OVERHEAD_LINE_WIDTH,
    )
    ax_timeseries.plot(
        analysis.time_axis,
        analysis.data_flood_series.tolist(),
        label='Flooded Data Relay',
        color=DATA_FLOOD_COLOR,
        linewidth=OVERHEAD_LINE_WIDTH,
        linestyle='--',
    )
    if analysis.control_series.sum() > 0:
        ax_timeseries.plot(
            analysis.time_axis,
            analysis.control_series.tolist(),
            label='NLSR Control Load',
            color=CONTROL_COLOR,
            linewidth=OVERHEAD_LINE_WIDTH,
            linestyle=':',
        )

    for index, handoff_time in enumerate(_parse_handoff_times(handoff_times_arg)):
        label = 'Handoff Window' if index == 0 else None
        ax_timeseries.axvspan(
            handoff_time,
            handoff_time + window,
            color='orange',
            alpha=HANDOFF_SHADE_ALPHA,
            label=label,
        )

    ax_timeseries.set_xlabel('Time (seconds)')
    ax_timeseries.set_ylabel('Relay Load (bytes/s)')
    _set_nonnegative_ylim_with_headroom(
        ax_timeseries,
        [
            float(analysis.interest_other_series.max()),
            float(analysis.interest_flood_series.max()),
            float(analysis.data_other_series.max()),
            float(analysis.data_flood_series.max()),
            float(analysis.control_series.max()),
        ],
        explicit_max=explicit_max,
    )
    ax_timeseries.xaxis.set_major_locator(MaxNLocator(nbins=X_TICK_BINS, integer=True))
    ax_timeseries.grid(True, which='both', ls='--')
    _populate_header_axis(ax_timeseries_header, ax_timeseries, 'Network Overhead Time Series')
    timeseries_fig.savefig(output_path, bbox_inches='tight')
    plt.close(timeseries_fig)


def _write_summary_plot(
    output_path: str | None,
    analysis: OverheadAnalysis,
    explicit_max: Optional[float],
) -> None:
    """Write the overhead summary figure to the requested PDF output."""
    if output_path is None:
        return
    _ensure_parent_dir(output_path)
    summary_items = analysis.handoff_summaries if analysis.handoff_summaries else [analysis.full_run_summary]
    interest_other = [item.interest_relay_bytes - item.interest_flood_bytes for item in summary_items]
    interest_flood = [item.interest_flood_bytes for item in summary_items]
    data_other = [item.data_relay_bytes - item.data_flood_bytes for item in summary_items]
    data_flood = [item.data_flood_bytes for item in summary_items]
    control_bytes = [item.control_bytes for item in summary_items]

    x = np.arange(len(summary_items))
    interest_positions = x - SUMMARY_BAR_WIDTH
    data_positions = x
    control_positions = x + SUMMARY_BAR_WIDTH
    summary_fig, ax_summary_header, ax_summary = _create_figure_with_header(
        SUMMARY_FIGURE_HEIGHT_CM,
        SUMMARY_FIGURE_BOTTOM_MARGIN,
    )

    ax_summary.bar(
        interest_positions,
        interest_other,
        SUMMARY_BAR_WIDTH,
        label='Non-flood Interest Relay',
        color=INTEREST_OTHER_COLOR,
    )
    ax_summary.bar(
        interest_positions,
        interest_flood,
        SUMMARY_BAR_WIDTH,
        bottom=interest_other,
        label='Flooded Interest Relay',
        color=INTEREST_FLOOD_COLOR,
    )
    ax_summary.bar(
        data_positions,
        data_other,
        SUMMARY_BAR_WIDTH,
        label='Non-flood Data Relay',
        color=DATA_OTHER_COLOR,
    )
    ax_summary.bar(
        data_positions,
        data_flood,
        SUMMARY_BAR_WIDTH,
        bottom=data_other,
        label='Flooded Data Relay',
        color=DATA_FLOOD_COLOR,
    )
    ax_summary.bar(
        control_positions,
        control_bytes,
        SUMMARY_BAR_WIDTH,
        label='NLSR Control',
        color=CONTROL_COLOR,
        alpha=0.75,
        hatch='//',
    )

    ymax = max(
        [item.interest_relay_bytes for item in summary_items] +
        [item.data_relay_bytes for item in summary_items] +
        [item.control_bytes for item in summary_items] +
        [1]
    )
    summary_tick_labels = [_format_summary_tick_label(summary) for summary in summary_items]
    ax_summary.set_xticks(x)
    ax_summary.set_xticklabels(summary_tick_labels)
    ax_summary.tick_params(axis='x', pad=1.5)
    ax_summary.set_ylabel('Bytes in Window')
    _set_nonnegative_ylim_with_headroom(ax_summary, [float(ymax)], explicit_max=explicit_max)
    ax_summary.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax_summary.grid(True, axis='y', linestyle='--', alpha=0.7)

    _populate_header_axis(ax_summary_header, ax_summary, 'Window Summaries')
    summary_fig.savefig(output_path, bbox_inches='tight')
    plt.close(summary_fig)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze and plot network forwarding overhead from unified multi-node NDN CSV."
    )
    parser.add_argument('--input', type=str, required=True, help='Input CSV file extracted from node pcaps.')
    parser.add_argument('--output-dir', type=str, help='Legacy directory used to derive default output files.')
    parser.add_argument('--timeseries-output', type=str, help='Path to the overhead time-series PDF output.')
    parser.add_argument('--summary-output', type=str, help='Path to the overhead summary PDF output.')
    parser.add_argument('--metrics-output', type=str, help='Path to the overhead metrics text output.')
    parser.add_argument('--handoff-times', type=str, help='Comma-separated list of handoff event times in seconds.')
    parser.add_argument('--window', type=float, default=10.0, help='Time window in seconds after a handoff for summary metrics.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to include.')
    parser.add_argument('--relay-nodes', type=str, default=','.join(DEFAULT_RELAY_NODES),
                        help='Comma-separated relay nodes counted in the forwarding-cost numerator.')
    parser.add_argument('--consumer-node', type=str, default='consumer',
                        help='Consumer node name used for delivered-data reference.')
    parser.add_argument('--timeseries-y-max', type=float,
                        help='Shared y-axis upper bound for the time-series overhead figure.')
    parser.add_argument('--summary-y-max', type=float,
                        help='Shared y-axis upper bound for the summary overhead figure.')
    parser.add_argument('--limits-file', type=str,
                        help='Path to a text file containing shared time-series and summary y-axis limits.')
    args = parser.parse_args()

    timeseries_output, summary_output, metrics_output = _resolve_output_paths(
        args.output_dir,
        args.timeseries_output,
        args.summary_output,
        args.metrics_output,
    )
    _configure_paper_style()

    if args.limits_file:
        args.timeseries_y_max, args.summary_y_max = _load_limits_file(args.limits_file)

    try:
        analysis = _load_analysis(
            args.input,
            args.prefix,
            args.relay_nodes,
            args.consumer_node,
            args.handoff_times,
            args.window,
        )
    except ValueError as exc:
        print(f"Warning: {exc} Cannot generate overhead plot.")
        _write_empty_outputs(timeseries_output, summary_output, metrics_output)
        return

    _write_timeseries_plot(
        timeseries_output,
        analysis,
        args.handoff_times,
        args.window,
        args.timeseries_y_max,
    )
    _write_summary_plot(
        summary_output,
        analysis,
        args.summary_y_max,
    )
    if metrics_output is not None:
        _ensure_parent_dir(metrics_output)
        _write_summary_file(
            metrics_output,
            analysis.relay_nodes,
            args.consumer_node,
            args.window,
            analysis.handoff_summaries,
            analysis.full_run_summary,
        )

    print("Generated overhead outputs")


if __name__ == '__main__':
    main()
