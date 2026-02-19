import pandas as pd
import argparse
import os
import bisect
import matplotlib.pyplot as plt

def normalize_name(name: str) -> str:
    """
    Keep only the canonical data name part before signer metadata.
    Example:
      /example/LiveStream/54=%01,/localhost/operator/KEY/... -> /example/LiveStream/54=%01
    """
    return str(name).split(',', 1)[0].strip()


def calculate_unmet_ratio(requests_df: pd.DataFrame) -> float:
    """Calculates unmet-interest ratio from request records containing `met` bool."""
    total = len(requests_df)
    if total == 0:
        return 0.0
    unmet = int((~requests_df['met']).sum())
    return unmet / total

def main():
    parser = argparse.ArgumentParser(description="Calculate and compare Unmet-Interest ratio from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save the output files.')
    parser.add_argument('--handoff-times', type=str, required=True, help='Comma-separated list of handoff event times.')
    parser.add_argument('--window', type=float, default=10.0, help='Analysis window duration in seconds after each handoff.')
    parser.add_argument('--prefix', type=str, default='/example/LiveStream', help='Application prefix to include.')
    parser.add_argument('--deadline', type=float, default=6.0,
                        help='Deadline in seconds to consider an Interest satisfied by Data.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. No loss calculated.")
        with open(os.path.join(args.output_dir, 'loss_ratio.txt'), 'w') as f:
            f.write("Handoff Window Ratio: 1.0\n")
            f.write("Steady State Ratio: 1.0\n")
        open(os.path.join(args.output_dir, 'loss_comparison.pdf'), 'w').close()
        return

    df.rename(columns={'frame.time_epoch': 'time', 'ndn.type': 'type', 'ndn.name': 'name'}, inplace=True)
    df = df.dropna(subset=['time', 'type', 'name']).copy()
    df['time'] = pd.to_numeric(df['time'], errors='coerce')
    df = df.dropna(subset=['time'])
    app_prefix = args.prefix
    df = df[df['name'].astype(str).str.startswith(app_prefix)]
    df = df[~df['name'].astype(str).str.startswith('/localhost/')]
    df = df[~df['name'].astype(str).str.startswith('/localhop/ndn/nlsr/')]
    if df.empty:
        print(f"Warning: No packets under prefix {app_prefix}. No loss calculated.")
        with open(os.path.join(args.output_dir, 'loss_ratio.txt'), 'w') as f:
            f.write("Handoff Window Ratio: 1.0\n")
            f.write("Steady State Ratio: 1.0\n")
        open(os.path.join(args.output_dir, 'loss_comparison.pdf'), 'w').close()
        return

    df['type'] = df['type'].str.lower()
    df = df[df['type'].isin(['interest', 'data'])].copy()
    if df.empty:
        print("Warning: No Interest/Data packets after filtering. No loss calculated.")
        with open(os.path.join(args.output_dir, 'loss_ratio.txt'), 'w') as f:
            f.write("Handoff Window Ratio: 1.0\n")
            f.write("Steady State Ratio: 1.0\n")
        open(os.path.join(args.output_dir, 'loss_comparison.pdf'), 'w').close()
        return
    df['base_name'] = df['name'].apply(normalize_name)

    start_time = df['time'].min()

    handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]

    interests = df[df['type'] == 'interest'][['time', 'base_name']].sort_values('time')
    data = df[df['type'] == 'data'][['time', 'base_name']].sort_values('time')
    if interests.empty:
        print("Warning: No Interests after filtering. No loss calculated.")
        with open(os.path.join(args.output_dir, 'loss_ratio.txt'), 'w') as f:
            f.write("Handoff Window Ratio: 1.0\n")
            f.write("Steady State Ratio: 1.0\n")
        open(os.path.join(args.output_dir, 'loss_comparison.pdf'), 'w').close()
        return

    first_requests = interests.groupby('base_name', as_index=False)['time'].min()
    data_times_by_name = {
        name: grp['time'].tolist()
        for name, grp in data.groupby('base_name')
    }

    records = []
    for _, row in first_requests.iterrows():
        name = row['base_name']
        req_time = float(row['time'])
        data_times = data_times_by_name.get(name, [])
        idx = bisect.bisect_left(data_times, req_time)
        data_time = data_times[idx] if idx < len(data_times) else None
        met = data_time is not None and (data_time - req_time) <= args.deadline
        records.append({
            'base_name': name,
            'request_time': req_time,
            'data_time': data_time,
            'met': met,
            'relative_time': req_time - start_time,
        })
    requests_df = pd.DataFrame.from_records(records)

    # --- (R2) Unmet-Interest ratio (K2) ---
    handoff_mask = pd.Series(False, index=requests_df.index)
    for t_h in handoffs:
        window_start = t_h
        window_end = t_h + args.window
        handoff_mask |= ((requests_df['relative_time'] >= window_start) &
                         (requests_df['relative_time'] < window_end))

    handoff_df = requests_df[handoff_mask]
    steady_state_df = requests_df[~handoff_mask]

    handoff_ratio = calculate_unmet_ratio(handoff_df)
    steady_state_ratio = calculate_unmet_ratio(steady_state_df)
    handoff_total = len(handoff_df)
    steady_total = len(steady_state_df)
    handoff_unmet = int((~handoff_df['met']).sum()) if handoff_total else 0
    steady_unmet = int((~steady_state_df['met']).sum()) if steady_total else 0

    # Save metrics to text file
    output_file = os.path.join(args.output_dir, 'loss_ratio.txt')
    with open(output_file, 'w') as f:
        f.write(f"Handoff Window Ratio: {handoff_ratio:.4f}\n")
        f.write(f"Steady State Ratio: {steady_state_ratio:.4f}\n")
        f.write(f"Handoff Requests: {handoff_total}\n")
        f.write(f"Handoff Unmet: {handoff_unmet}\n")
        f.write(f"Steady Requests: {steady_total}\n")
        f.write(f"Steady Unmet: {steady_unmet}\n")
        f.write(f"Deadline Seconds: {args.deadline:.2f}\n")
    
    # --- Paired Comparison Plot ---
    fig, ax = plt.subplots(figsize=(8, 6))
    labels = ['During Handoffs', 'Steady State']
    ratios = [handoff_ratio, steady_state_ratio]
    ax.bar(labels, ratios, color=['orangered', 'deepskyblue'])
    ax.set_ylabel('Unmet-Interest Ratio')
    ax.set_title(f'Comparison of Unmet-Interest Ratio (deadline={args.deadline:.1f}s)')
    ax.set_ylim(0, max(1.0, max(ratios) * 1.2))
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    for i, v in enumerate(ratios):
        ax.text(i, v + 0.02, f"{v:.3f}", ha='center', va='bottom')
        
    fig.tight_layout()
    plt.savefig(os.path.join(args.output_dir, 'loss_comparison.pdf'))
    plt.close(fig)

    print(f"Generated R2 (Unmet-Interest Ratio) metrics and plot in {args.output_dir}")

if __name__ == '__main__':
    main()
