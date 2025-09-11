import pandas as pd
import argparse
import os
import re

def parse_seq_num(name):
    """Parses sequence number from an NDN name."""
    if name is None:
        return None
    match = re.search(r'(?:/v=|\/)(\d+)$', name)
    if match:
        return int(match.group(1))
    return None

def main():
    parser = argparse.ArgumentParser(description="Calculate unsatisfied interest ratio from NDN pcap CSV.")
    parser.add_argument('--input', type=str, required=True, help='Input CSV file from tshark.')
    parser.add_argument('--output-dir', type=str, default='.', help='Directory to save the output metric.')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    try:
        df = pd.read_csv(args.input)
        if df.empty:
            raise pd.errors.EmptyDataError
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. No loss calculated.")
        with open(os.path.join(args.output_dir, 'loss_ratio.txt'), 'w') as f:
            f.write("1.0\n") # Assume 100% loss
        return

    df.rename(columns={'frame.time_epoch': 'time', 'ndn.type': 'type', 'ndn.name': 'name'}, inplace=True)
    df = df.dropna().copy()
    
    # Filter out NLSR sync packets, which are not part of the experiment data
    df = df[~df['name'].str.startswith('/localhop/ndn/nlsr/sync')]
    
    # Convert type to lowercase string
    df['type'] = df['type'].str.lower()
    
    df['seq'] = df['name'].apply(parse_seq_num)
    df = df.dropna(subset=['seq'])
    df['seq'] = df['seq'].astype(int)

    interests_sent = df[df['type'] == 'interest']['seq'].nunique()
    data_received = df[df['type'] == 'data']['seq'].nunique()

    if interests_sent == 0:
        print("Warning: No application interests were sent. Cannot calculate loss ratio.")
        loss_ratio = 1.0
    else:
        loss_ratio = 1.0 - (data_received / interests_sent)
    
    output_file = os.path.join(args.output_dir, 'loss_ratio.txt')
    with open(output_file, 'w') as f:
        f.write(str(loss_ratio))
    
    print(f"Unsatisfied Interest Ratio: {loss_ratio:.4f}")
    print(f"Result saved to {output_file}")

if __name__ == '__main__':
    main()
