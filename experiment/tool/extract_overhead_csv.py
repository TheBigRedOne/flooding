#!/usr/bin/env python3
"""
Convert per-node OptoFlood pcaps into a unified packet-level CSV.

The output CSV is the single analysis input for network-overhead plots.
Each row represents one decoded packet observation on one node.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


BASE_TSHARK_FIELDS: List[str] = [
    "frame.number",
    "frame.time_epoch",
    "frame.len",
    "sll.pkttype",
    "sll.ifindex",
    "ndn.type",
    "ndn.name",
    "ndn.hoplimit",
]

OUTPUT_FIELDS: List[str] = [
    "node",
    "frame.number",
    "frame.time_epoch",
    "frame.len",
    "sll.pkttype",
    "sll.ifindex",
    "ndn.type",
    "ndn.name",
    "ndn.flood_id",
    "ndn.new_face_seq",
    "ndn.lp.hoplimit",
    "ndn.lp.mobility_flag",
    "ndn.hoplimit",
]

_PCAP_MAGIC = {
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
    b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
    b"\x4d\x3c\xb2\xa1": (">", 1_000_000_000),
    b"\xa1\xb2<\x4d": ("<", 1_000_000_000),
}
_LINKTYPE_ETHERNET = 1
_LINKTYPE_LINUX_SLL = 113
_LINKTYPE_LINUX_SLL2 = 276
_ETHERTYPE_IPV4 = 0x0800
_ETHERTYPE_IPV6 = 0x86DD
_ETHERTYPE_NDN = 0x8624
_IPPROTO_UDP = 17
_LP_PACKET_TLV = 100
_LP_FRAGMENT_TLV = 80
_LP_OPTO_HOP_TLV = 96
_LP_OPTO_MOBILITY_TLV = 97
_NDN_INTEREST_TLV = 0x05
_NDN_DATA_TLV = 0x06
_TLV_METAINFO = 0x14
_TLV_FLOOD_ID = 202
_TLV_NEW_FACE_SEQ = 203
_TLV_INTEREST_HOPLIMIT = 34


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract a unified OptoFlood overhead CSV from per-node pcaps."
    )
    parser.add_argument(
        "--pcap-dir",
        required=True,
        help="Directory containing per-node *.pcap files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output CSV path.",
    )
    parser.add_argument(
        "--tshark",
        default="tshark",
        help="Path to tshark executable.",
    )
    return parser.parse_args()


def _read_var_num(buf: bytes, offset: int) -> Tuple[int, int]:
    if offset >= len(buf):
        raise ValueError("var-num overflow")
    first = buf[offset]
    if first < 253:
        return first, offset + 1
    if first == 253:
        if offset + 3 > len(buf):
            raise ValueError("var-num truncated")
        return int.from_bytes(buf[offset + 1:offset + 3], "big"), offset + 3
    if first == 254:
        if offset + 5 > len(buf):
            raise ValueError("var-num truncated")
        return int.from_bytes(buf[offset + 1:offset + 5], "big"), offset + 5
    if offset + 9 > len(buf):
        raise ValueError("var-num truncated")
    return int.from_bytes(buf[offset + 1:offset + 9], "big"), offset + 9


def _read_tlv(buf: bytes, offset: int) -> Tuple[int, bytes, int]:
    tlv_type, offset = _read_var_num(buf, offset)
    length, offset = _read_var_num(buf, offset)
    end = offset + length
    if end > len(buf):
        raise ValueError("tlv truncated")
    return tlv_type, buf[offset:end], end


def _iter_pcap_frames(pcap_path: Path) -> Iterator[Tuple[float, bytes, int]]:
    if not pcap_path.exists():
        return
    with pcap_path.open("rb") as fp:
        header = fp.read(24)
        if len(header) < 24:
            return
        magic = header[:4]
        if magic not in _PCAP_MAGIC:
            return
        endian, ts_scale = _PCAP_MAGIC[magic]
        _, _, _, _, _, network = struct.unpack(f"{endian}HHiiii", header[4:24])
        while True:
            pkt_hdr = fp.read(16)
            if len(pkt_hdr) < 16:
                break
            ts_sec, ts_usec, incl_len, _ = struct.unpack(f"{endian}IIII", pkt_hdr)
            data = fp.read(incl_len)
            if len(data) < incl_len:
                break
            yield ts_sec + ts_usec / ts_scale, data, network


def _parse_link_header(frame: bytes, linktype: int) -> Optional[Tuple[Optional[int], Optional[int], int, bytes]]:
    if linktype == _LINKTYPE_LINUX_SLL2:
        if len(frame) < 20:
            return None
        protocol = (frame[0] << 8) | frame[1]
        ifindex = int.from_bytes(frame[4:8], "big")
        pkttype = frame[10]
        return pkttype, ifindex, protocol, frame[20:]
    if linktype == _LINKTYPE_LINUX_SLL:
        if len(frame) < 16:
            return None
        pkttype = (frame[0] << 8) | frame[1]
        protocol = (frame[14] << 8) | frame[15]
        return pkttype, None, protocol, frame[16:]
    if linktype == _LINKTYPE_ETHERNET:
        if len(frame) < 14:
            return None
        eth_type = (frame[12] << 8) | frame[13]
        return None, None, eth_type, frame[14:]
    return None


def _extract_ndn_payload(eth_type: int, payload: bytes) -> Optional[bytes]:
    if eth_type == _ETHERTYPE_NDN:
        return payload
    if eth_type == _ETHERTYPE_IPV4:
        if len(payload) < 20:
            return None
        ihl = (payload[0] & 0x0F) * 4
        if len(payload) < ihl + 8 or payload[9] != _IPPROTO_UDP:
            return None
        return payload[ihl + 8:]
    if eth_type == _ETHERTYPE_IPV6:
        if len(payload) < 48 or payload[6] != _IPPROTO_UDP:
            return None
        return payload[48:]
    return None


def _parse_interest_hoplimit(inner_value: bytes) -> Optional[int]:
    offset = 0
    try:
        while offset < len(inner_value):
            sub_type, sub_value, offset = _read_tlv(inner_value, offset)
            if sub_type == _TLV_INTEREST_HOPLIMIT:
                if not sub_value:
                    return None
                return int.from_bytes(sub_value, "big")
    except ValueError:
        return None
    return None


def _parse_data_metadata(inner_value: bytes) -> Tuple[Optional[int], Optional[int]]:
    offset = 0
    flood_id = None
    new_face_seq = None
    try:
        while offset < len(inner_value):
            sub_type, sub_value, offset = _read_tlv(inner_value, offset)
            if sub_type != _TLV_METAINFO:
                continue
            meta_offset = 0
            while meta_offset < len(sub_value):
                meta_type, meta_value, meta_offset = _read_tlv(sub_value, meta_offset)
                if meta_type == _TLV_FLOOD_ID:
                    flood_id = int.from_bytes(meta_value, "big")
                elif meta_type == _TLV_NEW_FACE_SEQ:
                    new_face_seq = int.from_bytes(meta_value, "big")
    except ValueError:
        return flood_id, new_face_seq
    return flood_id, new_face_seq


def _decode_custom_fields(ndn_payload: bytes) -> Dict[str, str]:
    decoded: Dict[str, str] = {
        "ndn.flood_id": "",
        "ndn.new_face_seq": "",
        "ndn.lp.hoplimit": "",
        "ndn.lp.mobility_flag": "",
        "ndn.hoplimit": "",
    }

    try:
        tlv_type, tlv_value, _ = _read_tlv(ndn_payload, 0)
    except ValueError:
        return decoded

    inner_type = tlv_type
    inner_value = tlv_value

    if tlv_type == _LP_PACKET_TLV:
        offset = 0
        fragment = None
        try:
            while offset < len(tlv_value):
                sub_type, sub_value, offset = _read_tlv(tlv_value, offset)
                if sub_type == _LP_OPTO_HOP_TLV:
                    decoded["ndn.lp.hoplimit"] = str(int.from_bytes(sub_value, "big"))
                elif sub_type == _LP_OPTO_MOBILITY_TLV:
                    decoded["ndn.lp.mobility_flag"] = "1"
                elif sub_type == _LP_FRAGMENT_TLV:
                    fragment = sub_value
        except ValueError:
            return decoded
        if fragment is None:
            return decoded
        try:
            inner_type, inner_value, _ = _read_tlv(fragment, 0)
        except ValueError:
            return decoded

    if inner_type == _NDN_INTEREST_TLV:
        hoplimit = _parse_interest_hoplimit(inner_value)
        if hoplimit is not None:
            decoded["ndn.hoplimit"] = str(hoplimit)
        return decoded

    if inner_type == _NDN_DATA_TLV:
        flood_id, new_face_seq = _parse_data_metadata(inner_value)
        if flood_id is not None:
            decoded["ndn.flood_id"] = str(flood_id)
        if new_face_seq is not None:
            decoded["ndn.new_face_seq"] = str(new_face_seq)
        return decoded

    return decoded


def _extract_custom_fields_by_frame(pcap_path: Path) -> Dict[int, Dict[str, str]]:
    by_frame: Dict[int, Dict[str, str]] = {}
    for frame_no, (_, frame, linktype) in enumerate(_iter_pcap_frames(pcap_path), start=1):
        parsed = _parse_link_header(frame, linktype)
        if parsed is None:
            continue
        _, _, eth_type, payload = parsed
        ndn_payload = _extract_ndn_payload(eth_type, payload)
        if ndn_payload is None:
            continue
        by_frame[frame_no] = _decode_custom_fields(ndn_payload)
    return by_frame


def build_tshark_cmd(tshark: str, pcap_path: Path) -> List[str]:
    cmd = [tshark, "-r", str(pcap_path), "-T", "fields"]
    for field in BASE_TSHARK_FIELDS:
        cmd += ["-e", field]
    cmd += [
        "-E",
        "separator=,",
        "-E",
        "header=n",
        "-E",
        "quote=d",
        "-E",
        "occurrence=f",
    ]
    return cmd


def iter_pcaps(pcap_dir: Path) -> Iterable[Path]:
    return sorted(pcap_dir.glob("*.pcap"))


def extract_base_rows(tshark: str, pcap_path: Path) -> List[Dict[str, str]]:
    cmd = build_tshark_cmd(tshark, pcap_path)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"tshark failed for {pcap_path}: {result.stderr.strip() or 'unknown error'}"
        )

    rows: List[Dict[str, str]] = []
    reader = csv.reader(io.StringIO(result.stdout))
    for record in reader:
        if not record:
            continue
        record += [""] * (len(BASE_TSHARK_FIELDS) - len(record))
        row = dict(zip(BASE_TSHARK_FIELDS, record[:len(BASE_TSHARK_FIELDS)]))
        if not row["frame.number"].strip():
            continue
        rows.append(row)
    return rows


def main() -> int:
    args = parse_args()

    pcap_dir = Path(args.pcap_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pcaps = list(iter_pcaps(pcap_dir))
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        if not pcaps:
            print(f"Warning: no node pcaps found under {pcap_dir}", file=sys.stderr)
            return 0

        for pcap_path in pcaps:
            node_name = pcap_path.stem
            custom_by_frame = _extract_custom_fields_by_frame(pcap_path)
            for base_row in extract_base_rows(args.tshark, pcap_path):
                frame_number = int(base_row["frame.number"])
                custom_fields = custom_by_frame.get(frame_number, {})
                output_row = {
                    "node": node_name,
                    "frame.number": base_row.get("frame.number", ""),
                    "frame.time_epoch": base_row.get("frame.time_epoch", ""),
                    "frame.len": base_row.get("frame.len", ""),
                    "sll.pkttype": base_row.get("sll.pkttype", ""),
                    "sll.ifindex": base_row.get("sll.ifindex", ""),
                    "ndn.type": base_row.get("ndn.type", ""),
                    "ndn.name": base_row.get("ndn.name", ""),
                    "ndn.flood_id": custom_fields.get("ndn.flood_id", ""),
                    "ndn.new_face_seq": custom_fields.get("ndn.new_face_seq", ""),
                    "ndn.lp.hoplimit": custom_fields.get("ndn.lp.hoplimit", ""),
                    "ndn.lp.mobility_flag": custom_fields.get("ndn.lp.mobility_flag", ""),
                    "ndn.hoplimit": custom_fields.get("ndn.hoplimit", "") or base_row.get("ndn.hoplimit", ""),
                }
                writer.writerow(output_row)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
