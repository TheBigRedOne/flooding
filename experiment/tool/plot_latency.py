import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import argparse
import re
import os

def parse_info_column(infos):
    """Parses the 'Info' column from tshark CSV output into types and names."""
    types = []
    names = []
    # Regex to capture packet type (Interest, Data, Nack) and the rest as the name
    info_regex = re.compile(r'^(Interest|Data|Nack)\s+(.+)$')
    for s in infos:
        match = info_regex.match(str(s))
        if match:
            types.append(match.group(1).lower())
            names.append(match.group(2).strip())
        else:
            types.append(None)
            names.append(None)
    return types, names

def parse_seq_num(name):
    """Parses sequence number from an NDN name."""
    # Matches /v=123 or segment number /123
    match = re.search(r'(?:/v=|\/)(\d+)$', name)
    if match:
        return int(match.group(1))
    return None

def main():
    parser = argparse.ArgumentParser(description="Analyze latency from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save output plots.')
    parser.add_argument('--handoff-times', type=str, help='Comma-separated list of handoff event times in seconds.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    plt.style.use('seaborn-v0_8-whitegrid')
    
    try:
        df = pd.read_csv(args.input)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. Skipping.")
        return

    # Create a clean DataFrame from the raw tshark output
    types, names = parse_info_column(df['Info'])
    clean_df = pd.DataFrame({
        'time': pd.to_numeric(df['Time'], errors='coerce'),
        'type': types,
        'name': names
    }).dropna()

    clean_df['seq'] = clean_df['name'].apply(parse_seq_num)
    clean_df = clean_df.dropna(subset=['seq'])
    clean_df['seq'] = clean_df['seq'].astype(int)

    interests = clean_df[clean_df['type'] == 'interest'].drop_duplicates(subset=['seq'], keep='first').set_index('seq')['time']
    datas = clean_df[clean_df['type'] == 'data'].drop_duplicates(subset=['seq'], keep='first').set_index('seq')['time']
    
    rtt_df = pd.concat([interests, datas], axis=1, keys=['interest_time', 'data_time']).dropna()
    rtt_df['rtt_ms'] = (rtt_df['data_time'] - rtt_df['interest_time']) * 1000.0
    
    rtt_df = rtt_df[(rtt_df['rtt_ms'] >= 0) & (rtt_df['rtt_ms'] < 10000)] # RTT < 10s

    if rtt_df.empty:
        print("Warning: No matching Interest/Data pairs found. Cannot generate latency plots.")
        return

    start_time = clean_df['time'].min()
    rtt_df['relative_time'] = rtt_df['data_time'] - start_time

    # --- Plot Latency Time-Series ---
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(rtt_df['relative_time'], rtt_df['rtt_ms'], marker='o', linestyle='-', markersize=2, alpha=0.7, label='Segment RTT')
    
    if args.handoff_times:
        handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]
        for i, t in enumerate(handoffs):
            label = f'Handoff at {t}s' if i == 0 else None
            ax.axvline(x=t, color='r', linestyle='--', label=label)

    ax.set_xlabel('Time (seconds)')
    ax.set_ylabel('End-to-End Latency (ms)')
    ax.set_title('Segment Latency Over Time')
    ax.legend()
    ax.set_yscale('log')
    ax.set_ylim(bottom=1)
    fig.tight_layout()
    plt.savefig(os.path.join(args.output_dir, 'latency_timeseries.pdf'))
    plt.close(fig)

    # --- Plot Latency CDF ---
    fig, ax = plt.subplots(figsize=(10, 6))
    sorted_rtt = np.sort(rtt_df['rtt_ms'])
    yvals = np.arange(1, len(sorted_rtt) + 1) / len(sorted_rtt)
    ax.plot(sorted_rtt, yvals, marker='.', markersize=4, linestyle='none', label='RTT CDF')
    
    ax.set_xlabel('End-to-End Latency (ms)')
    ax.set_ylabel('Cumulative Probability')
    ax.set_title('Latency CDF')
    ax.legend()
    ax.set_xscale('log')
    ax.grid(True, which="both", ls="--")
    fig.tight_layout()
    plt.savefig(os.path.join(args.output_dir, 'latency_cdf.pdf'))
    plt.close(fig)
    print(f"Generated latency plots in {args.output_dir}")

if __name__ == '__main__':
    main()
