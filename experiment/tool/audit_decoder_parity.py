#!/usr/bin/env python3
"""Compare a tshark-derived overhead CSV with the Python pcap decoder.

Every differing field is reported. Mismatches are not dropped.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import mobility_event_metrics as metrics

KEY_FIELDS = (
    "frame.time_epoch",
    "frame.len",
    "sll.pkttype",
    "ndn.type",
    "ndn.name",
    "ndn.flood_id",
    "ndn.lp.hoplimit",
    "ndn.lp.mobility_flag",
    "ndn.hoplimit",
)


def row_mismatches(reference: Dict[str, str], candidate: Dict[str, str]) -> List[str]:
    """Return one entry per field that is not semantically equal."""
    found: List[str] = []
    for field in KEY_FIELDS:
        left = (reference.get(field) or "").strip()
        right = (candidate.get(field) or "").strip()
        if field == "frame.time_epoch":
            if abs(float(left) - float(right)) > 1e-6:
                found.append(f"{field}: tshark={left} python={right}")
            continue
        if field == "frame.len":
            if int(float(left)) != int(float(right)):
                found.append(f"{field}: tshark={left} python={right}")
            continue
        if field == "ndn.type":
            if left.lower() != right.lower():
                found.append(f"{field}: tshark={left} python={right}")
            continue
        if field == "ndn.name":
            if metrics.canonical_name(left) != metrics.canonical_name(right):
                found.append(f"{field}: tshark={metrics.canonical_name(left)} python={metrics.canonical_name(right)}")
            continue
        if field == "sll.pkttype":
            if left != right:
                found.append(f"{field}: tshark={left} python={right}")
            continue
        if left != right:
            found.append(f"{field}: tshark={left} python={right}")
    left_name = metrics.canonical_name(reference.get("ndn.name") or "")
    right_name = metrics.canonical_name(candidate.get("ndn.name") or "")
    if metrics.is_nlsr(left_name) != metrics.is_nlsr(right_name):
        found.append(f"nlsr_class: tshark={metrics.is_nlsr(left_name)} python={metrics.is_nlsr(right_name)}")
    return found


def index_reference(path: Path) -> Dict[Tuple[str, str], Dict[str, str]]:
    indexed: Dict[Tuple[str, str], Dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            indexed[(row.get("node") or "", row.get("frame.number") or "")] = row
    return indexed


def compare_indexed(reference: Dict[Tuple[str, str], Dict[str, str]], candidate_rows: Iterable[Dict[str, str]], sample_limit: int = 20) -> str:
    matched = 0
    missing_in_python = 0
    extra_in_python = 0
    mismatch_rows = 0
    by_field: Dict[str, int] = {}
    samples: List[str] = []
    seen = set()
    for row in candidate_rows:
        key = (row.get("node") or "", row.get("frame.number") or "")
        seen.add(key)
        original = reference.get(key)
        if original is None:
            extra_in_python += 1
            if len(samples) < sample_limit:
                samples.append(f"EXTRA {key}")
            continue
        matched += 1
        mismatches = row_mismatches(original, row)
        if not mismatches:
            continue
        mismatch_rows += 1
        for item in mismatches:
            field = item.split(":", 1)[0]
            by_field[field] = by_field.get(field, 0) + 1
        if len(samples) < sample_limit:
            samples.append(f"MISMATCH {key} " + "; ".join(mismatches))
    for key in reference:
        if key not in seen:
            missing_in_python += 1
            if len(samples) < sample_limit:
                samples.append(f"MISSING {key}")
    lines = [
        f"reference_rows={len(reference)} matched={matched} missing_in_python={missing_in_python} "
        f"extra_in_python={extra_in_python} mismatch_rows={mismatch_rows}",
        "mismatches_by_field=" + ", ".join(f"{field}:{count}" for field, count in sorted(by_field.items())),
    ]
    lines.extend(samples)
    return "\n".join(lines)


def candidate_rows_from_pcaps(pcap_dir: Path, decode_row) -> Iterable[Dict[str, str]]:
    import extract_overhead_csv as extractor
    for pcap in sorted(pcap_dir.glob("*.pcap")):
        for frame_no, (timestamp, frame, linktype) in enumerate(extractor._iter_pcap_frames(pcap), start=1):
            parsed = extractor._parse_link_header(frame, linktype)
            if parsed is None:
                continue
            pkttype, _ifindex, protocol, payload = parsed
            ndn_payload = extractor._extract_ndn_payload(protocol, payload)
            if ndn_payload is None:
                continue
            name, ptype, custom = decode_row(ndn_payload)
            if not name:
                continue
            yield {
                "node": pcap.stem,
                "frame.number": str(frame_no),
                "frame.time_epoch": f"{timestamp:.9f}",
                "frame.len": str(len(frame)),
                "sll.pkttype": "" if pkttype is None else str(pkttype),
                "ndn.type": ptype,
                "ndn.name": name,
                "ndn.flood_id": custom.get("ndn.flood_id", ""),
                "ndn.lp.hoplimit": custom.get("ndn.lp.hoplimit", ""),
                "ndn.lp.mobility_flag": custom.get("ndn.lp.mobility_flag", ""),
                "ndn.hoplimit": custom.get("ndn.hoplimit", ""),
            }
