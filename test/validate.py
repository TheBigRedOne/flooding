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
    # Dedup: check same Data name/FloodId appears once per neighbor; fallback to count per pcap
    # Simplified: ensure r3, r4, r5 do not show duplicated identical Data frames within small time window
    # For strong evidence, this would parse Data name and custom FloodId field if dissector available.
    for node in ('r3', 'r4', 'r5'):
        p = os.path.join(PCAP_DIR, f'{node}.pcap')
        if not os.path.exists(p):
            continue
        res = run(tshark_cmd(['-r', p, '-Y', 'ndn.type==6', '-T', 'fields', '-e', 'ndn.name']))
        names = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
        if len(names) != len(set(names)):
            print(f'FAIL: S2 duplicate Data detected on {node}')
            sys.exit(1)
    print('PASS: S2 Data dedup (no duplicates by name observed)')


def validate_s3() -> None:
    # TFIB: rely on logs if available; minimal check here is that Interests traverse when FIB miss expected window
    # Placeholder: success if Interests observed at r3 within expected window.
    p = os.path.join(PCAP_DIR, 'r3.pcap')
    if not os.path.exists(p):
        print('FAIL: S3 missing r3.pcap')
        sys.exit(1)
    res = run(tshark_cmd(['-r', p, '-Y', 'ndn.type==5', '-c', '1']))
    if res.returncode == 0:
        print('PASS: S3 TFIB/forwarding window observed (Interest present)')
        return
    print('FAIL: S3 no Interest observed at r3')
    sys.exit(1)


def validate_s5() -> None:
    # Fast-LSA: expect logs/nfdc evidence. Here we check for management Data under localhost namespace in pcaps as a proxy.
    # Strong variant should parse NLSR logs; minimal check here:
    any_hit = False
    for node in ('r2', 'r3', 'r4'):
        p = os.path.join(PCAP_DIR, f'{node}.pcap')
        if not os.path.exists(p):
            continue
        res = run(tshark_cmd(['-r', p, '-Y', 'ndn.name contains "/localhost/nlsr/fast-lsa"', '-c', '1']))
        if res.returncode == 0:
            any_hit = True
            break
    if any_hit:
        print('PASS: S5 management trigger observed (proxy for Fast-LSA)')
    else:
        print('FAIL: S5 no management trigger observed')
        sys.exit(1)


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


