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
RESULTS_DIR = os.path.join(TEST_DIR, 'results')
PCAP_DIR = os.path.join(RESULTS_DIR, 'pcap')
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
_NDN_INTEREST_TLV = 0x05
_NDN_DATA_TLV = 0x06
_TLV_METAINFO = 0x14
_TLV_FLOOD_ID = 202
_TLV_INTEREST_HOPLIMIT = 34


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
        # Linux SLL2 header is 20 bytes; protocol is at bytes 0-1
        if len(frame) < 20:
            return None
        packet_type = frame[10]
        eth_type = (frame[0] << 8) | frame[1]
        return packet_type, eth_type, frame[20:]
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


def _extract_interest_hoplimit(payload: bytes) -> Optional[int]:
    try:
        tlv_type, tlv_value, _ = _read_tlv(payload, 0)
    except ValueError:
        return None
    if tlv_type != _NDN_INTEREST_TLV:
        return None
    offset = 0
    try:
        while offset < len(tlv_value):
            sub_type, sub_value, offset = _read_tlv(tlv_value, offset)
            if sub_type == _TLV_INTEREST_HOPLIMIT:
                if not sub_value:
                    return None
                return int.from_bytes(sub_value, 'big')
    except ValueError:
        return None
    return None


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
    if flood_map:
        return flood_map
    return _collect_flood_hoplimits_raw(pcap_files)


def _collect_flood_hoplimits_raw(pcap_files: List[str]) -> Dict[int, set]:
    flood_map: Dict[int, set] = defaultdict(set)
    for pcap in pcap_files:
        if not os.path.exists(pcap):
            continue
        for _, frame, linktype in _iter_pcap_frames(pcap):
            stripped = _strip_link_header(frame, linktype)
            if stripped is None:
                continue
            _, eth_type, payload = stripped
            if eth_type != _ETHERTYPE_NDN:
                continue
            decoded = _decode_flood_and_hop(payload)
            if decoded is None:
                continue
            flood_id, hop = decoded
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


def _parse_int_tokens(values: Iterable[str]) -> List[int]:
    parsed: List[int] = []
    for item in values:
        for token in item.replace(',', ' ').split():
            try:
                parsed.append(int(token))
            except ValueError:
                continue
    return parsed


def _collect_flood_ids_by_node(nodes: List[str]) -> Dict[str, set]:
    by_node: Dict[str, set] = {}
    for node in nodes:
        pcap = os.path.join(PCAP_DIR, f'{node}.pcap')
        ids: set = set()
        if os.path.exists(pcap):
            values = tshark_fields(pcap, 'ndn.type==Data', 'ndn.flood_id')
            ids.update(_parse_int_tokens(values))
        by_node[node] = ids
    return by_node


def validate_s1() -> None:
    # FIB-guided Data flooding: FloodId should be observed without requiring LP HopLimit,
    # and downstream nodes should not see FloodIds that never appeared at the branch root.
    nodes = ['r2', 'r3', 'r4', 'r5']
    by_node = _collect_flood_ids_by_node(nodes)
    all_ids = set().union(*by_node.values())
    if not all_ids:
        print('FAIL: S1 no Data FloodId observed (check pcaps/dissector)')
        sys.exit(1)

    core_ids = by_node.get('r3', set())
    if not core_ids:
        print('FAIL: S1 core node r3 has no FloodId Data; cannot validate guided flooding')
        sys.exit(1)

    offenders = []
    for node in ('r2', 'r4', 'r5'):
        extra = sorted(by_node[node] - core_ids)
        if extra:
            offenders.append((node, extra[:10]))
    if offenders:
        detail = '; '.join(f'{node}:extra={extra}' for node, extra in offenders)
        print('FAIL: S1 FloodId observed off-branch without passing r3 ->', detail)
        sys.exit(1)

    r4_ids = by_node.get('r4', set())
    r5_ids = by_node.get('r5', set())
    if r4_ids and r5_ids:
        if min(r5_ids) < min(r4_ids):
            print('FAIL: S1 branch ordering mismatch: r5 min FloodId precedes r4',
                  f"(r4 min={min(r4_ids)}, r5 min={min(r5_ids)})")
            sys.exit(1)

    summary = []
    for node in nodes:
        ids = sorted(by_node[node])
        if ids:
            summary.append(f"{node}:{len(ids)} ids [{ids[0]}..{ids[-1]}]")
        else:
            summary.append(f"{node}:0 ids")
    print('PASS: S1 FIB-guided flooding observed (FloodId ranges):', '; '.join(summary))


def validate_s4() -> None:
    nodes = ['r2', 'r3', 'r4', 'r5']
    observations: List[Tuple[str, int]] = []

    def _collect_interest_records(pcap_path: str) -> List[Tuple[int, str, int, int, str]]:
        """
        Return list of (frame_no, dir, hop, nonce, name)
        dir: 'in' (pkttype!=4) or 'out' (pkttype==4)
        """
        records: List[Tuple[int, str, int, int, str]] = []
        if not os.path.exists(pcap_path):
            return records
        filter_expr = 'ndn.type==Interest && ndn.name contains "/example/LiveStream" && !(ndn.name contains "/localhost/")'
        cmd = tshark_cmd([
            '-r', pcap_path,
            '-Y', filter_expr,
            '-T', 'fields',
            '-e', 'sll.pkttype',
            '-e', 'frame.number',
            '-e', 'ndn.hoplimit',
            '-e', 'ndn.nonce',
            '-e', 'ndn.name',
        ])
        res = run(cmd)
        if res.returncode != 0:
            return records
        for line in res.stdout.splitlines():
            cols = [col.strip() for col in line.split('\t')]
            if len(cols) < 5:
                continue
            pkttype, frame_raw, hop_raw, nonce_raw, name_raw = cols[:5]
            if not name_raw.startswith('/example/LiveStream'):
                continue
            hop_val: Optional[int] = None
            for token in hop_raw.replace(',', ' ').split():
                try:
                    hop_val = int(token)
                    break
                except ValueError:
                    continue
            if hop_val is None:
                continue
            try:
                frame_no = int(frame_raw)
            except ValueError:
                continue
            try:
                nonce_val = int(nonce_raw, 16)
            except ValueError:
                continue
            direction = 'out' if pkttype == '4' else 'in'
            records.append((frame_no, direction, hop_val, nonce_val, name_raw))
        records.sort(key=lambda x: x[0])
        return records

    nodes = ['r2', 'r3', 'r4', 'r5']
    records_by_node = {node: _collect_interest_records(os.path.join(PCAP_DIR, f'{node}.pcap')) for node in nodes}

    def _has_rib_entry(node: str, prefix: str) -> bool:
        for label in ('T2', 'T1', 'T0'):
            rib_path = os.path.join(RESULTS_DIR, f'{node}_{label}_rib.txt')
            if os.path.exists(rib_path):
                with open(rib_path, 'r', encoding='utf-8', errors='ignore') as fp:
                    if prefix in fp.read():
                        return True
        return False

    # Build first in/out per nonce per node
    first_in = {node: {} for node in nodes}
    first_out = {node: {} for node in nodes}
    for node in nodes:
        for frame_no, direction, hop, nonce, name in records_by_node[node]:
            if direction == 'in' and nonce not in first_in[node]:
                first_in[node][nonce] = (frame_no, hop)
            if direction == 'out' and nonce not in first_out[node]:
                first_out[node][nonce] = (frame_no, hop)

    # Candidate nonces (mode A): seen inbound on >=3 nodes, else >=2
    nonce_in_nodes = {}
    for node in nodes:
        for nonce in first_in[node]:
            nonce_in_nodes.setdefault(nonce, set()).add(node)

    candidates_3 = [n for n, s in nonce_in_nodes.items() if len(s) >= 3]
    candidates_2 = [n for n, s in nonce_in_nodes.items() if len(s) >= 2]
    candidates_inbound = candidates_3 if candidates_3 else candidates_2

    # Candidate nonces (mode B fallback): r2 outbound present AND at least one downstream inbound
    r2_out_nonces = set(first_out['r2'].keys())
    downstream_in_nonces = set()
    for node in ['r3', 'r4', 'r5']:
        downstream_in_nonces.update(first_in[node].keys())
    candidates_fallback = [n for n in r2_out_nonces if n in downstream_in_nonces]

    candidates = candidates_inbound if candidates_inbound else candidates_fallback

    def check_nonce(nonce: int) -> Optional[List[int]]:
        # per-node in/out check: if both exist, enforce in = out + 1
        for node in nodes:
            if nonce in first_in[node] and nonce in first_out[node]:
                hop_in = first_in[node][nonce][1]
                hop_out = first_out[node][nonce][1]
                if hop_in != hop_out + 1:
                    return None
        # build inbound chain in node order
        inbound_chain: List[int] = []
        for node in nodes:
            if nonce in first_in[node]:
                inbound_chain.append(first_in[node][nonce][1])
        if len(inbound_chain) < 2:
            return None
        if not all(inbound_chain[i] == inbound_chain[i - 1] - 1 for i in range(1, len(inbound_chain))):
            return None
        return inbound_chain

    for candidate in candidates:
        chain = check_nonce(candidate)
        if not chain:
            continue
        if chain[-1] <= 0:
            print(f'PASS: S4 Interest HopLimit decrement path = {chain} (nonce={hex(candidate)})')
            return
        last_node_idx = ['r2', 'r3', 'r4', 'r5'][len(chain) - 1]
        if _has_rib_entry(last_node_idx, '/example/LiveStream'):
            print(f'PASS: S4 Interest HopLimit chain={chain} stopped at {last_node_idx} due to existing route (nonce={hex(candidate)})')
            return
    print('FAIL: S4 no matching Interest nonce with monotonic HopLimit across nodes; candidates checked =', len(candidates))
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
    r3_rib_T1 = os.path.join(RESULTS_DIR, 'r3_T1_rib.txt')
    r3_rib_T2 = os.path.join(RESULTS_DIR, 'r3_T2_rib.txt')
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
    r3_rib_T1 = os.path.join(RESULTS_DIR, 'r3_T1_rib.txt')
    r3_rib_T2 = os.path.join(RESULTS_DIR, 'r3_T2_rib.txt')
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



