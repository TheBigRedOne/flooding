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
PAPER_FIGURE_HEIGHT_CM = 8.0

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
LEGEND_VERTICAL_OFFSET = 1.05
APP_TOTAL_COLOR = 'crimson'
FLOOD_COLOR = 'darkorange'
APP_OTHER_COLOR = 'steelblue'
CONTROL_COLOR = 'slateblue'
DEFAULT_RELAY_NODES = ['core', 'agg1', 'agg2', 'acc1', 'acc2', 'acc3', 'acc4', 'acc5', 'acc6']
LOCALHOST_PREFIX = '/localhost/'


@dataclass
class WindowSummary:
    label: str
    app_relay_packets: int
    app_relay_bytes: int
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
        "legend.fontsize": LEGEND_SIZE,
        "figure.titlesize": FIGURE_TITLE_SIZE,
    })
    plt.rcParams["pdf.use14corefonts"] = True
    plt.rcParams["font.family"] = "serif"


def _place_legend_above_axis(ax) -> None:
    """Place the legend above the axis to avoid covering plotted series and bars."""
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    ax.legend(
        handles,
        labels,
        loc='lower center',
        bbox_to_anchor=(0.5, LEGEND_VERTICAL_OFFSET),
        ncol=min(len(handles), LEGEND_MAX_COLUMNS),
        frameon=False,
        borderaxespad=0.0,
        columnspacing=0.8,
        handlelength=1.5,
        handletextpad=0.5,
    )


def _write_empty_outputs(output_dir: str) -> None:
    open(os.path.join(output_dir, 'overhead_timeseries.pdf'), 'w').close()
    with open(os.path.join(output_dir, 'overhead_total.txt'), 'w', encoding='utf-8') as output_file:
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
    relay_flood_out: pd.DataFrame,
    relay_interest_flood_out: pd.DataFrame,
    relay_data_flood_out: pd.DataFrame,
    relay_control_out: pd.DataFrame,
    delivered_data_in: pd.DataFrame,
) -> WindowSummary:
    if start is None or end is None:
        app_df = relay_app_out
        flood_df = relay_flood_out
        interest_flood_df = relay_interest_flood_out
        data_flood_df = relay_data_flood_out
        control_df = relay_control_out
        delivered_df = delivered_data_in
    else:
        app_df = relay_app_out[(relay_app_out['relative_time'] >= start) & (relay_app_out['relative_time'] < end)]
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
            output_file.write(f"Explicit Flood Packets: {summary.flood_packets}\n")
            output_file.write(f"Explicit Flood Bytes: {summary.flood_bytes}\n")
            output_file.write(f"Interest Flood Bytes: {summary.interest_flood_bytes}\n")
            output_file.write(f"Data Flood Bytes: {summary.data_flood_bytes}\n")
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


def main():
    parser = argparse.ArgumentParser(
        description="Analyze and plot network forwarding overhead from unified multi-node NDN CSV."
    )
    parser.add_argument('--input', type=str, required=True, help='Input CSV file extracted from node pcaps.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save output files.')
    parser.add_argument('--handoff-times', type=str, help='Comma-separated list of handoff event times in seconds.')
    parser.add_argument('--window', type=float, default=10.0, help='Time window in seconds after a handoff for summary metrics.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to include.')
    parser.add_argument('--relay-nodes', type=str, default=','.join(DEFAULT_RELAY_NODES),
                        help='Comma-separated relay nodes counted in the forwarding-cost numerator.')
    parser.add_argument('--consumer-node', type=str, default='consumer',
                        help='Consumer node name used for delivered-data reference.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    _configure_paper_style()

    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping.")
        _write_empty_outputs(args.output_dir)
        return

    df = _normalize_columns(df)
    required_cols = {'node', 'time', 'length', 'type', 'name'}
    if not required_cols.issubset(set(df.columns)):
        missing = sorted(required_cols - set(df.columns))
        print(f"Warning: Missing required columns {missing}. Cannot generate overhead plot.")
        _write_empty_outputs(args.output_dir)
        return

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
        df['name'].str.startswith(args.prefix) &
        ~df['is_control'] &
        ~df['is_localhost']
    )
    if not df['is_app'].any():
        print("Warning: No app traffic found. Cannot generate overhead plot.")
        _write_empty_outputs(args.output_dir)
        return

    start_time = float(df.loc[df['is_app'], 'time'].min())
    df['relative_time'] = df['time'] - start_time
    df = df[df['relative_time'] >= 0].copy()
    if df.empty:
        print("Warning: No packets remain after aligning to app start time.")
        _write_empty_outputs(args.output_dir)
        return

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

    relay_nodes = _parse_relay_nodes(args.relay_nodes)
    relay_mask = df['node'].isin(relay_nodes)

    relay_app_out = df[relay_mask & df['is_outbound'] & df['is_app']].copy()
    relay_flood_out = df[relay_mask & df['is_outbound'] & df['is_explicit_flood']].copy()
    relay_interest_flood_out = df[relay_mask & df['is_outbound'] & df['is_interest_flood']].copy()
    relay_data_flood_out = df[relay_mask & df['is_outbound'] & df['is_data_flood']].copy()
    relay_control_out = df[relay_mask & df['is_outbound'] & df['is_control']].copy()
    delivered_data_in = df[
        (df['node'] == args.consumer_node) &
        df['is_inbound'] &
        df['is_app_data']
    ].copy()

    if relay_app_out.empty:
        print("Warning: No relay outbound app traffic after filtering. Cannot generate overhead plot.")
        _write_empty_outputs(args.output_dir)
        return

    max_second = int(max(
        relay_app_out['second'].max() if not relay_app_out.empty else 0,
        relay_control_out['second'].max() if not relay_control_out.empty else 0,
        delivered_data_in['second'].max() if not delivered_data_in.empty else 0,
    ))
    max_second = max(max_second, 0)

    relay_app_series = _aggregate_bytes_per_second(relay_app_out, max_second)
    relay_flood_series = _aggregate_bytes_per_second(relay_flood_out, max_second)
    relay_control_series = _aggregate_bytes_per_second(relay_control_out, max_second)
    time_axis = list(range(max_second + 1))

    handoff_times = _parse_handoff_times(args.handoff_times)
    handoff_summaries = [
        _summarize_window(
            f'Handoff {index + 1}',
            handoff_time,
            handoff_time + args.window,
            relay_app_out,
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
        relay_flood_out,
        relay_interest_flood_out,
        relay_data_flood_out,
        relay_control_out,
        delivered_data_in,
    )

    fig, (ax_timeseries, ax_summary) = plt.subplots(
        2,
        1,
        figsize=_paper_figure_size(),
        gridspec_kw={'height_ratios': [1.8, 1.2]},
    )

    ax_timeseries.plot(
        time_axis,
        relay_app_series.tolist(),
        label='App Relay Load',
        color=APP_TOTAL_COLOR,
        linewidth=OVERHEAD_LINE_WIDTH,
    )
    ax_timeseries.plot(
        time_axis,
        relay_flood_series.tolist(),
        label='Explicit Flood Load',
        color=FLOOD_COLOR,
        linewidth=OVERHEAD_LINE_WIDTH,
    )
    if relay_control_series.sum() > 0:
        ax_timeseries.plot(
            time_axis,
            relay_control_series.tolist(),
            label='NLSR Control Load',
            color=CONTROL_COLOR,
            linewidth=OVERHEAD_LINE_WIDTH,
            linestyle='--',
        )

    for index, handoff_time in enumerate(handoff_times):
        label = 'Handoff Window' if index == 0 else None
        ax_timeseries.axvspan(
            handoff_time,
            handoff_time + args.window,
            color='orange',
            alpha=HANDOFF_SHADE_ALPHA,
            label=label,
        )

    full_run_box = "\n".join([
        "Full Run",
        f"FCR={_format_ratio(full_run_summary.forwarding_cost_ratio)}",
        f"Flood={_format_ratio(full_run_summary.flood_share, percent=True)}",
        f"Control={full_run_summary.control_bytes} B",
    ])
    ax_timeseries.text(
        0.02,
        0.98,
        full_run_box,
        transform=ax_timeseries.transAxes,
        ha='left',
        va='top',
        bbox={'boxstyle': 'round', 'facecolor': 'white', 'alpha': 0.85, 'edgecolor': '0.8'},
    )

    ax_timeseries.set_xlabel('Time (seconds)')
    ax_timeseries.set_ylabel('Relay Load (bytes/s)')
    ax_timeseries.set_title('Network Overhead Over Time')
    ax_timeseries.set_ylim(bottom=0)
    ax_timeseries.xaxis.set_major_locator(MaxNLocator(nbins=X_TICK_BINS, integer=True))
    _place_legend_above_axis(ax_timeseries)
    ax_timeseries.grid(True, which='both', ls='--')

    summary_items = handoff_summaries if handoff_summaries else [full_run_summary]
    summary_labels = [item.label for item in summary_items]
    other_forwarding = [item.app_relay_bytes - item.flood_bytes for item in summary_items]
    explicit_flood = [item.flood_bytes for item in summary_items]
    control_bytes = [item.control_bytes for item in summary_items]

    x = np.arange(len(summary_items))
    app_positions = x - SUMMARY_BAR_WIDTH / 2
    control_positions = x + SUMMARY_BAR_WIDTH / 2

    ax_summary.bar(
        app_positions,
        other_forwarding,
        SUMMARY_BAR_WIDTH,
        label='Other App Forwarding',
        color=APP_OTHER_COLOR,
    )
    ax_summary.bar(
        app_positions,
        explicit_flood,
        SUMMARY_BAR_WIDTH,
        bottom=other_forwarding,
        label='Explicit Flood',
        color=FLOOD_COLOR,
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
        [item.app_relay_bytes for item in summary_items] +
        [item.control_bytes for item in summary_items] +
        [1]
    )
    label_offset = max(ymax * 0.04, 1.0)
    for index, summary in enumerate(summary_items):
        top = max(summary.app_relay_bytes, summary.control_bytes)
        ax_summary.text(
            x[index],
            top + label_offset,
            f"FCR={_format_ratio(summary.forwarding_cost_ratio)}\n"
            f"Flood={_format_ratio(summary.flood_share, percent=True)}",
            ha='center',
            va='bottom',
        )

    ax_summary.set_xticks(x)
    ax_summary.set_xticklabels(summary_labels)
    ax_summary.set_ylabel('Bytes in Window')
    ax_summary.set_title('Window Summaries')
    ax_summary.set_ylim(0, ymax + label_offset * 3.0)
    ax_summary.yaxis.set_major_locator(MaxNLocator(nbins=4))
    _place_legend_above_axis(ax_summary)
    ax_summary.grid(True, axis='y', linestyle='--', alpha=0.7)

    fig.tight_layout(h_pad=1.2)
    fig.savefig(os.path.join(args.output_dir, 'overhead_timeseries.pdf'), bbox_inches='tight')
    plt.close(fig)

    _write_summary_file(
        os.path.join(args.output_dir, 'overhead_total.txt'),
        relay_nodes,
        args.consumer_node,
        args.window,
        handoff_summaries,
        full_run_summary,
    )

    print(f"Generated overhead plot and metrics in {args.output_dir}")


if __name__ == '__main__':
    main()
