#!/usr/bin/env python3
"""
Purpose: Strong validation for S1–S5 using tshark JSON and logs.
Interface:
  python3 validate.py s1|s2|s3|s4|s5
Outputs:
  Prints PASS/FAIL and minimal evidence paths. Returns non-zero on FAIL.
"""

import json
import os
import subprocess
import sys
from typing import List

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PCAP_DIR = os.path.join(TEST_DIR, 'pcap')
# Load custom dissector explicitly for tshark
LUA_DISS = os.path.abspath(os.path.join(TEST_DIR, '..', 'experiment', 'tool', 'ndn.lua'))


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)


def tshark_cmd(extra: List[str]) -> List[str]:
    args = ['tshark']
    if os.path.exists(LUA_DISS):
        args += ['-X', f'lua_script:{LUA_DISS}']
    args += extra
    return args


def tshark_json(pcap: str, fields: List[str]) -> List[dict]:
    cmd = tshark_cmd(['-r', pcap, '-T', 'json'])
    res = run(cmd)
    if res.returncode != 0:
        print(f"FAIL: tshark error on {pcap}: {res.stderr}")
        sys.exit(1)
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        print(f"FAIL: cannot decode tshark JSON from {pcap}")
        sys.exit(1)
    return data


def tshark_fields(pcap: str, display_filter: str, field: str) -> List[str]:
    cmd = tshark_cmd(['-r', pcap, '-Y', display_filter, '-T', 'fields', '-e', field])
    res = run(cmd)
    if res.returncode != 0:
        return []
    return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]


def extract_hoplimits(json_packets: List[dict], is_data: bool) -> List[int]:
    hoplimits = []
    for pkt in json_packets:
        layers = pkt.get('_source', {}).get('layers', {})
        # Prefer LP:OptoHopLimit for Data (custom dissector may expose as ndn.lp.hoplimit)
        if is_data:
            # Try candidate fields
            for key in ('ndn.lp.hoplimit', 'ndn_lp_hoplimit', 'ndn.optop_hoplimit'):
                if key in layers:
                    v = layers[key]
                    try:
                        hoplimits.append(int(v[0]))
                    except Exception:
                        pass
                    break
        else:
            # Interest native HopLimit
            for key in ('ndn.hoplimit', 'ndn_interest_hoplimit'):
                if key in layers:
                    v = layers[key]
                    try:
                        hoplimits.append(int(v[0]))
                    except Exception:
                        pass
                    break
    return hoplimits


def validate_s1() -> None:
    # Expect Data OptoHopLimit to decrement across path and stop at 0 within <=4 hops.
    path_pcaps = [
        os.path.join(PCAP_DIR, 'r2.pcap'),
        os.path.join(PCAP_DIR, 'r3.pcap'),
        os.path.join(PCAP_DIR, 'r4.pcap'),
        os.path.join(PCAP_DIR, 'r5.pcap'),
    ]
    seen = []
    for p in path_pcaps:
        if not os.path.exists(p):
            continue
        # Prefer direct field extraction for robustness
        vals = tshark_fields(p, 'ndn.type==6', 'ndn.lp.hoplimit')
        if vals:
            try:
                seen.append(int(vals[0]))
                continue
            except Exception:
                pass
        # Fallback to JSON scan
        j = tshark_json(p, [])
        hls = extract_hoplimits(j, is_data=True)
        if hls:
            seen.append(hls[0])
    if not seen:
        print('FAIL: no Data hoplimit observed')
        sys.exit(1)
    # Check monotonic decrement by 1 and last <= 0
    ok = True
    for i in range(1, len(seen)):
        if seen[i] != seen[i - 1] - 1:
            ok = False
            break
    if ok and seen[-1] <= 0:
        print('PASS: S1 Data OptoHopLimit decrement path =', seen)
        return
    print('FAIL: S1 hoplimit sequence invalid =', seen)
    sys.exit(1)


def validate_s4() -> None:
    # Expect Interest HopLimit to decrement under miss
    path_pcaps = [
        os.path.join(PCAP_DIR, 'r2.pcap'),
        os.path.join(PCAP_DIR, 'r3.pcap'),
        os.path.join(PCAP_DIR, 'r4.pcap'),
        os.path.join(PCAP_DIR, 'r5.pcap'),
    ]
    seen = []
    for p in path_pcaps:
        if not os.path.exists(p):
            continue
        # Prefer direct field extraction for robustness
        vals = tshark_fields(p, 'ndn.type==5', 'ndn.hoplimit')
        if vals:
            try:
                seen.append(int(vals[0]))
                continue
            except Exception:
                pass
        # Fallback to JSON scan
        j = tshark_json(p, [])
        hls = extract_hoplimits(j, is_data=False)
        if hls:
            seen.append(hls[0])
    if not seen:
        print('FAIL: no Interest hoplimit observed')
        sys.exit(1)
    ok = True
    for i in range(1, len(seen)):
        if seen[i] != seen[i - 1] - 1:
            ok = False
            break
    if ok and seen[-1] <= 0:
        print('PASS: S4 Interest HopLimit decrement path =', seen)
        return
    print('FAIL: S4 hoplimit sequence invalid =', seen)
    sys.exit(1)


def validate_s2() -> None:
    # Strong dedup by FloodId (MetaInfo TLV 202) via custom dissector field ndn.flood_id
    any_checked = False
    for node in ('r3', 'r4', 'r5'):
        p = os.path.join(PCAP_DIR, f'{node}.pcap')
        if not os.path.exists(p):
            continue
        res = run(tshark_cmd(['-r', p, '-Y', 'ndn.type==6', '-T', 'fields', '-e', 'ndn.flood_id']))
        lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
        if lines:
            any_checked = True
            if len(lines) != len(set(lines)):
                print(f'FAIL: S2 duplicate FloodId detected on {node}')
                sys.exit(1)
    if not any_checked:
        print('FAIL: S2 no FloodId observed in pcaps (check dissector)')
        sys.exit(1)
    print('PASS: S2 Data dedup by FloodId (no duplicates)')


def validate_s3() -> None:
    # Strong TFIB window evidence via RIB snapshots (T1 vs T2) and Interest presence
    r3_rib_T1 = os.path.join(TEST_DIR, 'r3_T1_rib.txt')
    r3_rib_T2 = os.path.join(TEST_DIR, 'r3_T2_rib.txt')
    if not (os.path.exists(r3_rib_T1) and os.path.exists(r3_rib_T2)):
        print('FAIL: S3 missing RIB snapshots (r3_T1_rib.txt/r3_T2_rib.txt)')
        sys.exit(1)
    with open(r3_rib_T1, 'r', encoding='utf-8', errors='ignore') as f1, open(r3_rib_T2, 'r', encoding='utf-8', errors='ignore') as f2:
        t1 = f1.read()
        t2 = f2.read()
    if t1 == t2:
        print('FAIL: S3 RIB did not change across T1->T2 window')
        sys.exit(1)
    p = os.path.join(PCAP_DIR, 'r3.pcap')
    if os.path.exists(p):
        res = run(tshark_cmd(['-r', p, '-Y', 'ndn.type==5', '-c', '1']))
        if res.returncode != 0:
            print('FAIL: S3 no Interest observed at r3 during window')
            sys.exit(1)
    print('PASS: S3 TFIB window evidenced by RIB change and Interest presence')


def validate_s5() -> None:
    # Strong Fast-LSA check via RIB snapshots: detect short-lived route between T1 and T2
    r3_rib_T1 = os.path.join(TEST_DIR, 'r3_T1_rib.txt')
    r3_rib_T2 = os.path.join(TEST_DIR, 'r3_T2_rib.txt')
    if not (os.path.exists(r3_rib_T1) and os.path.exists(r3_rib_T2)):
        print('FAIL: S5 missing RIB snapshots (r3_T1_rib.txt/r3_T2_rib.txt)')
        sys.exit(1)
    with open(r3_rib_T1, 'r', encoding='utf-8', errors='ignore') as f1, open(r3_rib_T2, 'r', encoding='utf-8', errors='ignore') as f2:
        t1 = f1.read().splitlines()
        t2 = f2.read().splitlines()
    disappeared = [ln for ln in t1 if ln not in t2]
    if not disappeared:
        print('FAIL: S5 no short-lived RIB entries detected between T1 and T2')
        sys.exit(1)
    print('PASS: S5 short-lived RIB entries detected, count =', len(disappeared))


def main():
    if len(sys.argv) != 2:
        print('Usage: python3 validate.py [s1|s2|s3|s4|s5]')
        sys.exit(2)
    which = sys.argv[1].lower()
    if which == 's1':
        validate_s1()
    elif which == 's2':
        validate_s2()
    elif which == 's3':
        validate_s3()
    elif which == 's4':
        validate_s4()
    elif which == 's5':
        validate_s5()
    else:
        print('Unknown test id:', which)
        sys.exit(2)


if __name__ == '__main__':
    main()


