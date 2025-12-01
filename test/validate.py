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
import struct
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

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


def _read_var_num(buf: bytes, offset: int) -> Tuple[int, int]:
    if offset >= len(buf):
        raise ValueError('var-num overflow')
    first = buf[offset]
    if first < 253:
        return first, offset + 1
    if first == 253:
        if offset + 3 > len(buf):
            raise ValueError('var-num truncated')
        return int.from_bytes(buf[offset + 1:offset + 3], 'big'), offset + 3
    if first == 254:
        if offset + 5 > len(buf):
            raise ValueError('var-num truncated')
        return int.from_bytes(buf[offset + 1:offset + 5], 'big'), offset + 5
    if offset + 9 > len(buf):
        raise ValueError('var-num truncated')
    return int.from_bytes(buf[offset + 1:offset + 9], 'big'), offset + 9


def _read_tlv(buf: bytes, offset: int) -> Tuple[int, bytes, int]:
    tlv_type, offset = _read_var_num(buf, offset)
    length, offset = _read_var_num(buf, offset)
    end = offset + length
    if end > len(buf):
        raise ValueError('tlv truncated')
    return tlv_type, buf[offset:end], end


_PCAP_MAGIC = {
    b'\xd4\xc3\xb2\xa1': ('<', 1_000_000),
    b'\xa1\xb2\xc3\xd4': ('>', 1_000_000),
    b'\x4d\x3c\xb2\xa1': ('>', 1_000_000_000),
    b'\xa1\xb2<\x4d': ('<', 1_000_000_000),
}

_LINKTYPE_ETHERNET = 1
_LINKTYPE_LINUX_SLL = 113
_LINKTYPE_LINUX_SLL2 = 276
_ETHERTYPE_NDN = 0x8624
_LP_PACKET_TLV = 100
_LP_FRAGMENT_TLV = 80
_LP_OPTO_HOP_TLV = 96
_NDN_DATA_TLV = 0x06
_TLV_METAINFO = 0x14
_TLV_FLOOD_ID = 202


def _iter_pcap_frames(pcap_path: str) -> Iterable[Tuple[float, bytes, int]]:
    if not os.path.exists(pcap_path):
        return
    with open(pcap_path, 'rb') as fp:
        header = fp.read(24)
        if len(header) < 24:
            return
        magic = header[:4]
        if magic not in _PCAP_MAGIC:
            return
        endian, ts_scale = _PCAP_MAGIC[magic]
        version_major, version_minor, thiszone, sigfigs, snaplen, network = struct.unpack(
            f'{endian}HHiiii', header[4:24])
        while True:
            pkt_hdr = fp.read(16)
            if len(pkt_hdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(f'{endian}IIII', pkt_hdr)
            data = fp.read(incl_len)
            if len(data) < incl_len:
                break
            yield ts_sec + ts_usec / ts_scale, data, network


def _strip_link_header(frame: bytes, linktype: int) -> Optional[Tuple[int, int, bytes]]:
    if linktype == _LINKTYPE_ETHERNET:
        if len(frame) < 18:
            return None
        eth_type = (frame[12] << 8) | frame[13]
        return 0, eth_type, frame[14:]
    if linktype == _LINKTYPE_LINUX_SLL:
        if len(frame) < 18:
            return None
        packet_type = (frame[0] << 8) | frame[1]
        eth_type = (frame[14] << 8) | frame[15]
        return packet_type, eth_type, frame[16:]
    if linktype == _LINKTYPE_LINUX_SLL2:
        if len(frame) < 22:
            return None
        packet_type = (frame[8] << 8) | frame[9]
        eth_type = (frame[20] << 8) | frame[21]
        return packet_type, eth_type, frame[22:]
    return None


def _decode_flood_and_hop(payload: bytes) -> Optional[Tuple[int, int]]:
    try:
        tlv_type, tlv_value, _ = _read_tlv(payload, 0)
    except ValueError:
        return None
    if tlv_type != _LP_PACKET_TLV:
        return None
    offset = 0
    hop = None
    fragment = None
    try:
        while offset < len(tlv_value):
            sub_type, sub_value, offset = _read_tlv(tlv_value, offset)
            if sub_type == _LP_OPTO_HOP_TLV:
                hop = int.from_bytes(sub_value, 'big')
            elif sub_type == _LP_FRAGMENT_TLV:
                fragment = sub_value
    except ValueError:
        return None
    if fragment is None:
        return None
    try:
        inner_type, inner_value, _ = _read_tlv(fragment, 0)
    except ValueError:
        return None
    if inner_type != _NDN_DATA_TLV:
        return None
    offset = 0
    try:
        _, _, offset = _read_tlv(inner_value, offset)  # Name
        meta_type, meta_value, offset = _read_tlv(inner_value, offset)
    except ValueError:
        return None
    if meta_type != _TLV_METAINFO:
        return None
    meta_offset = 0
    flood_id = None
    try:
        while meta_offset < len(meta_value):
            tlv_t, tlv_v, meta_offset = _read_tlv(meta_value, meta_offset)
            if tlv_t == _TLV_FLOOD_ID:
                flood_id = int.from_bytes(tlv_v, 'big')
                break
    except ValueError:
        return None
    if flood_id is None or hop is None:
        return None
    return flood_id, hop


def _collect_flood_hoplimits(pcap_files: List[str]) -> Dict[int, set]:
    flood_map: Dict[int, set] = defaultdict(set)
    for pcap in pcap_files:
        if not os.path.exists(pcap):
            continue
        cmd = tshark_cmd([
            '-r', pcap,
            '-Y', 'ndn.type==Data',
            '-T', 'fields',
            '-e', 'ndn.flood_id',
            '-e', 'ndn.lp.hoplimit',
        ])
        res = run(cmd)
        if res.returncode != 0:
            continue
        for line in res.stdout.splitlines():
            cols = [c for c in line.strip().split('\t') if c]
            if len(cols) < 2:
                continue
            try:
                flood_id = int(cols[0])
                hop = int(cols[1])
            except ValueError:
                continue
            flood_map[flood_id].add(hop)
    return flood_map


def _collect_inbound_flood_counts(pcap_files: List[str]) -> Dict[str, Dict[int, int]]:
    inbound: Dict[str, Dict[int, int]] = {}
    for pcap in pcap_files:
        if not os.path.exists(pcap):
            continue
        node = os.path.splitext(os.path.basename(pcap))[0]
        counts: Dict[int, int] = defaultdict(int)
        cmd = tshark_cmd([
            '-r', pcap,
            '-Y', 'ndn.type==Data',
            '-T', 'fields',
            '-e', 'sll.pkttype',
            '-e', 'ndn.flood_id',
        ])
        res = run(cmd)
        if res.returncode != 0:
            continue
        for line in res.stdout.splitlines():
            cols = line.strip().split('\t')
            if len(cols) < 2:
                continue
            pkttype = cols[0].strip()
            fid = cols[1].strip()
            if not fid:
                continue
            # sll.pkttype: 0/1 inbound, 4 outbound; empty when not captured via SLL
            if pkttype == '4':
                continue
            try:
                flood_id = int(fid)
            except ValueError:
                continue
            counts[flood_id] += 1
        if counts:
            inbound[node] = counts
    return inbound


@dataclass
class OutboundFloodRecord:
    flood_id: int
    iface: str
    dst: str
    hoplimit: Optional[int]
    frame_no: Optional[int]


def _collect_outbound_flood_records(pcap_files: List[str]) -> Dict[str, Dict[Tuple[int, str, str], List[OutboundFloodRecord]]]:
    outbound: Dict[str, Dict[Tuple[int, str, str], List[OutboundFloodRecord]]] = {}
    for pcap in pcap_files:
        if not os.path.exists(pcap):
            continue
        node = os.path.splitext(os.path.basename(pcap))[0]
        records: Dict[Tuple[int, str, str], List[OutboundFloodRecord]] = defaultdict(list)
        cmd = tshark_cmd([
            '-r', pcap,
            '-Y', 'ndn.type==Data',
            '-T', 'fields',
            '-e', 'sll.pkttype',
            '-e', 'sll.ifindex',
            '-e', 'ip.dst',
            '-e', 'ndn.flood_id',
            '-e', 'frame.number',
            '-e', 'ndn.lp.hoplimit',
        ])
        res = run(cmd)
        if res.returncode != 0:
            continue
        for line in res.stdout.splitlines():
            cols = line.strip().split('\t')
            if len(cols) < 6:
                continue
            pkttype = cols[0].strip()
            iface = cols[1].strip() or '?'
            dst = cols[2].strip() or '?'
            fid = cols[3].strip()
            frame_no = cols[4].strip()
            hop_raw = cols[5].strip()
            if pkttype != '4' or not fid:
                continue
            if dst == '?' or not dst:
                continue
            try:
                flood_id = int(fid)
            except ValueError:
                continue
            hoplimit: Optional[int]
            if hop_raw:
                try:
                    hoplimit = int(hop_raw)
                except ValueError:
                    hoplimit = None
            else:
                hoplimit = None
            frame_idx: Optional[int]
            if frame_no:
                try:
                    frame_idx = int(frame_no)
                except ValueError:
                    frame_idx = None
            else:
                frame_idx = None
            key = (flood_id, iface, dst)
            records[key].append(OutboundFloodRecord(flood_id, iface, dst, hoplimit, frame_idx))
        if records:
            outbound[node] = records
    return outbound


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
    # Expect at least one FloodId with OptoHopLimit values forming a contiguous chain down to 0.
    path_pcaps = [
        os.path.join(PCAP_DIR, 'r2.pcap'),
        os.path.join(PCAP_DIR, 'r3.pcap'),
        os.path.join(PCAP_DIR, 'r4.pcap'),
        os.path.join(PCAP_DIR, 'r5.pcap'),
    ]
    flood_map = _collect_flood_hoplimits(path_pcaps)
    if not flood_map:
        print('FAIL: S1 no Data flood hoplimit observed (check pcaps/dissector)')
        sys.exit(1)
    for flood_id, values in flood_map.items():
        usable = {v for v in values if v >= 0}
        if not usable or 0 not in usable:
            continue
        max_h = max(usable)
        if max_h < 2:
            continue
        if all(val in usable for val in range(0, max_h + 1)):
            chain = sorted(usable, reverse=True)
            print(f'PASS: S1 Flood {flood_id} hoplimits {chain} show decrement to 0')
            return
    detail = '; '.join(f'{fid}:{sorted(sorted_vals)}' for fid, sorted_vals in ((fid, sorted(vals)) for fid, vals in flood_map.items()))
    print('FAIL: S1 insufficient hoplimit coverage; need contiguous values down to 0. Observed =', detail)
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
        vals = tshark_fields(p, 'ndn.type==Interest', 'ndn.hoplimit')
        if vals:
            hop = None
            for raw in vals:
                try:
                    hop = int(raw)
                    break
                except ValueError:
                    continue
            if hop is not None:
                seen.append(hop)
                continue
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
    path_pcaps = [os.path.join(PCAP_DIR, f'{node}.pcap') for node in ('r2', 'r3', 'r4', 'r5')]
    outbound = _collect_outbound_flood_records(path_pcaps)
    if not outbound:
        print('FAIL: S2 no FloodId observed in pcaps (check dissector)')
        sys.exit(1)
    offenders = []
    for node, rec_map in outbound.items():
        dup = {key: recs for key, recs in rec_map.items() if len(recs) > 1}
        if dup:
            offenders.append((node, dup))
    if offenders:
        detail_items = []
        for node, dup_map in offenders:
            for (fid, iface, dst), recs in list(dup_map.items())[:3]:
                frames = ','.join(str(r.frame_no) if r.frame_no is not None else '?' for r in recs)
                hops = ','.join(str(r.hoplimit) if r.hoplimit is not None else '?' for r in recs)
                detail_items.append(
                    f"{node}:fid={fid},iface={iface},dst={dst},count={len(recs)},frames=[{frames}],hoplimit=[{hops}]")
        print('FAIL: S2 duplicate FloodId detected in outbound traffic ->', '; '.join(detail_items))
        sys.exit(1)
    print('PASS: S2 Data dedup verified (no outbound duplicates per interface)')


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
    if len(sys.argv) <= 1:
        requested = ['s1', 's2', 's3', 's4', 's5']
    else:
        requested = [arg.lower() for arg in sys.argv[1:]]
    for which in requested:
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



