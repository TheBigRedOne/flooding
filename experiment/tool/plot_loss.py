import pandas as pd
import argparse
import os
import re
import matplotlib.pyplot as plt

def parse_seq_num(name):
    """Parses sequence number from an NDN name."""
    if name is None:
        return None
    match = re.search(r'(?:/v=|\/)(\d+)$', name)
    if match:
        return int(match.group(1))
    return None

def calculate_unmet_ratio(df_window):
    """Calculates the unmet interest ratio for a given dataframe window."""
    interests_sent = df_window[df_window['type'] == 'interest']['seq'].nunique()
    data_received = df_window[df_window['type'] == 'data']['seq'].nunique()
    if interests_sent == 0:
        return 0.0  # Avoid division by zero if no interests were sent in the window
    return 1.0 - (data_received / interests_sent)

def main():
    parser = argparse.ArgumentParser(description="Calculate and compare Unmet-Interest ratio from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save the output files.')
    parser.add_argument('--handoff-times', type=str, required=True, help='Comma-separated list of handoff event times.')
    parser.add_argument('--window', type=float, default=10.0, help='Analysis window duration in seconds after each handoff.')
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
    df = df.dropna().copy()
    df = df[~df['name'].str.startswith('/localhop/ndn/nlsr/sync')]
    df['type'] = df['type'].str.lower()
    df['seq'] = df['name'].apply(parse_seq_num)
    df = df.dropna(subset=['seq'])
    df['seq'] = df['seq'].astype(int)

    start_time = df['time'].min()
    df['relative_time'] = df['time'] - start_time
    
    handoffs = [float(t.strip()) for t in args.handoff_times.split(',')]
    
    # --- (R2) Unmet-Interest ratio (K2) ---
    handoff_windows = []
    steady_state_df = df.copy()

    for t_h in handoffs:
        window_start = t_h
        window_end = t_h + args.window
        handoff_window_df = df[(df['relative_time'] >= window_start) & (df['relative_time'] < window_end)]
        handoff_windows.append(handoff_window_df)
        # Exclude handoff windows from the steady_state_df
        steady_state_df = steady_state_df[~((steady_state_df['relative_time'] >= window_start) & (steady_state_df['relative_time'] < window_end))]

    if not handoff_windows:
        print("Warning: No handoff data to analyze.")
        handoff_ratio = 1.0
    else:
        combined_handoff_df = pd.concat(handoff_windows)
        handoff_ratio = calculate_unmet_ratio(combined_handoff_df)

    steady_state_ratio = calculate_unmet_ratio(steady_state_df)

    # Save metrics to text file
    output_file = os.path.join(args.output_dir, 'loss_ratio.txt')
    with open(output_file, 'w') as f:
        f.write(f"Handoff Window Ratio: {handoff_ratio:.4f}\n")
        f.write(f"Steady State Ratio: {steady_state_ratio:.4f}\n")
    
    # --- Paired Comparison Plot ---
    fig, ax = plt.subplots(figsize=(8, 6))
    labels = ['During Handoffs', 'Steady State']
    ratios = [handoff_ratio, steady_state_ratio]
    ax.bar(labels, ratios, color=['orangered', 'deepskyblue'])
    ax.set_ylabel('Unmet-Interest Ratio')
    ax.set_title('Comparison of Unmet-Interest Ratio')
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
