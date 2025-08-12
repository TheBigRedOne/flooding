import pandas as pd
import argparse
import re
import os

def parse_info_column(infos):
    """Parses the 'Info' column from tshark CSV output into types and names."""
    types = []
    names = []
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
    except (pd.errors.EmptyDataError, FileNotFoundError):
        print(f"Warning: Input file {args.input} is empty or not found. No loss calculated.")
        loss_ratio = 1.0 # Assume 100% loss
        return

    types, names = parse_info_column(df['Info'])
    clean_df = pd.DataFrame({
        'type': types,
        'name': names
    }).dropna()

    clean_df['seq'] = clean_df['name'].apply(parse_seq_num)
    clean_df = clean_df.dropna(subset=['seq'])
    clean_df['seq'] = clean_df['seq'].astype(int)

    interests_sent = clean_df[clean_df['type'] == 'interest']['seq'].nunique()
    data_received = clean_df[clean_df['type'] == 'data']['seq'].nunique()

    if interests_sent == 0:
        print("Warning: No interests were sent. Cannot calculate loss ratio.")
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
