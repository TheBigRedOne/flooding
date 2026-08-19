#!/usr/bin/env python3
"""Offline validator for pure-R2 runtime-gate artifacts.

  python3 validate_r2.py A|CF|R <results-dir>
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_NFD_VERSION = '24.07+git.56b8d8db'
OBSOLETE_PROOF_RETIRE = (
    r'OptoFlood tfib-retire prefix=\S+ reason=new-path-calculated\+fib-agrees'
)
PROBE_NAME = '/LiveStream/_r2probe'
NONCE_HEX = r'[0-9A-Fa-f]+'
HARD_DEADLINE_S = 120.0
HARD_DEADLINE_TOL_S = 1.0


def nonce_eq(left: str, right: str) -> bool:
    return left.lower() == right.lower()


class Check:
    def __init__(self, status: str, name: str, detail: str):
        self.status = status
        self.name = name
        self.detail = detail

    def line(self) -> str:
        return f'{self.status}: {self.name}: {self.detail}'


def load_events(results: str) -> List[Dict[str, Any]]:
    path = os.path.join(results, 'events.jsonl')
    if not os.path.isfile(path):
        return []
    events: List[Dict[str, Any]] = []
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return events


def find_event(events: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for rec in reversed(events):
        if rec.get('event') == name:
            return rec
    return None


def read_text(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.read()


def must_read(results: str, rel: str, checks: List[Check]) -> Optional[str]:
    path = os.path.join(results, rel)
    text = read_text(path)
    if text is None:
        checks.append(Check('FAIL', f'missing:{rel}', path))
        return None
    return text


def required_files(results: str, rels: List[str], checks: List[Check]) -> None:
    for rel in rels:
        must_read(results, rel, checks)


def nfd_log(results: str, node: str, checks: List[Check]) -> Optional[str]:
    return must_read(results, os.path.join('logs', f'{node}_nfd.log'), checks)


def parse_nfd_ts(line: str) -> Optional[float]:
    match = re.match(r'^(\d+)\.(\d{6})\b', line.strip())
    if not match:
        return None
    return float(match.group(1)) + float(match.group(2)) / 1_000_000.0


def require_events(results: str, checks: List[Check]) -> List[Dict[str, Any]]:
    events = load_events(results)
    if not events and not os.path.isfile(os.path.join(results, 'events.jsonl')):
        checks.append(Check('FAIL', 'missing:events.jsonl',
                            os.path.join(results, 'events.jsonl')))
    return events


def print_checks(checks: List[Check]) -> None:
    for check in checks:
        print(check.line())


def params_ok(results: str, cell: str, checks: List[Check]) -> None:
    params = must_read(results, 'params.txt', checks)
    version = must_read(results, 'nfd_version.txt', checks)
    if version is not None:
        actual = version.strip()
        if actual != REQUIRED_NFD_VERSION:
            checks.append(Check(
                'FAIL', 'nfd.version',
                f'required={REQUIRED_NFD_VERSION} actual={actual}'))
        else:
            checks.append(Check('PASS', 'nfd.version', actual))
    if params is None:
        return
    required = {
        'neighbors.event-driven-adjacency-verification': 'off',
        'neighbors.result-driven-adj-lsa-build': 'off',
        'neighbors.corridor-prioritised-routing': 'off',
        'cell': cell,
        'nfd.version': REQUIRED_NFD_VERSION,
    }
    parsed = {}
    for line in params.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            parsed[key.strip()] = value.strip()
    for key, value in required.items():
        actual = parsed.get(key)
        if actual != value:
            checks.append(Check('FAIL', f'params.{key}',
                                f'required={value} actual={actual}'))
        else:
            checks.append(Check('PASS', f'params.{key}', actual))
    if 'OPTOFLOOD_NLSR_VERIFY_NOW=1' in params:
        checks.append(Check('FAIL', 'verify-now',
                            'producer daemon must not receive OPTOFLOOD_NLSR_VERIFY_NOW=1'))
    else:
        checks.append(Check('PASS', 'verify-now', 'unset while event-driven is off'))


def check_no_proof_retire(log: str, checks: List[Check]) -> None:
    hits = re.findall(OBSOLETE_PROOF_RETIRE, log)
    if hits:
        checks.append(Check('FAIL', 'obsolete-proof-retire', f'count={len(hits)}'))
    else:
        checks.append(Check('PASS', 'obsolete-proof-retire',
                            'no new-path-calculated+fib-agrees retire'))


def check_telemetry_proof(log: str, checks: List[Check]) -> None:
    hits = re.findall(
        r'OptoFlood new-path-calculated prefix=\S+ serial=\d+ ignored reason=no-tfib-authority',
        log,
    )
    if hits:
        checks.append(Check('PASS', 'new-path-calculated-telemetry',
                            f'ignored reason=no-tfib-authority count={len(hits)}'))
    else:
        checks.append(Check('PASS', 'new-path-calculated-telemetry',
                            'absent (optional telemetry)'))


def parse_tfib_updates(log: str) -> List[Tuple[str, str, str]]:
    return re.findall(
        r'TFIB update prefix=(/LiveStream)\s+face=(\d+)\s+newFaceSeq=(\d+)',
        log,
    )


def exact_fib_hops(fib_text: str, prefix: str = '/LiveStream') -> List[str]:
    for line in fib_text.splitlines():
        stripped = line.strip()
        if re.match(rf'^{re.escape(prefix)}\s+nexthops=', stripped):
            return re.findall(r'faceid=(\d+)', stripped)
    return []


def parse_nlsr_hops(route_text: str) -> List[str]:
    return re.findall(r'nexthop=(\d+)\s+origin=(?:nlsr|128)\b', route_text, flags=re.IGNORECASE)


def validate_a(results: str) -> List[Check]:
    checks: List[Check] = []
    params_ok(results, 'A', checks)
    events = require_events(results, checks)
    required_files(results, [
        'producer.log', 'optoflood_producer.log', 'optoflood_consumer.log',
        os.path.join('logs', 'r1_nfd.log'),
        os.path.join('logs', 'r3_nfd.log'),
        os.path.join('logs', 'r2_nlsr.log'),
    ], checks)
    r2 = nfd_log(results, 'r2', checks)
    consumer = must_read(results, 'consumer.log', checks)
    if r2 is None:
        return checks
    check_no_proof_retire(r2, checks)
    check_telemetry_proof(r2, checks)

    updates = parse_tfib_updates(r2)
    if not updates:
        checks.append(Check('FAIL', 'tfib-update', 'no TFIB update prefix=/LiveStream on r2'))
        tfib_face = None
    else:
        _prefix, tfib_face, seq = updates[-1]
        checks.append(Check('PASS', 'tfib-update',
                            f'prefix=/LiveStream face={tfib_face} newFaceSeq={seq}'))

    if not re.search(r'OptoFlood tfib-forward interest=', r2):
        checks.append(Check('FAIL', 'tfib-forward-active',
                            'no Active TFIB use on r2'))
    else:
        checks.append(Check('PASS', 'tfib-forward-active', 'observed'))
        if tfib_face and re.search(
                rf'onOutgoingInterest out={tfib_face} interest=/LiveStream/', r2):
            checks.append(Check('PASS', 'outgoing-tfib-face',
                                f'out={tfib_face}'))
        else:
            checks.append(Check('FAIL', 'outgoing-tfib-face',
                                'no onOutgoingInterest out=<tfib-face> for /LiveStream'))

    standby_ev = find_event(events, 'tfib_standby')
    standby_log = bool(re.search(
        r'OptoFlood tfib-standby prefix=/LiveStream reason=fib-agrees', r2))
    if standby_ev or standby_log:
        checks.append(Check('PASS', 'tfib-standby',
                            (standby_ev or {}).get('line', 'log match')))
        fib_path = os.path.join(results, 'nfdc', 'r2_standby_fib.txt')
        if not os.path.isfile(fib_path):
            fib_path = os.path.join(results, 'nfdc', 'r2_standby_timeout_fib.txt')
        fib = read_text(fib_path)
        if fib is None:
            checks.append(Check('FAIL', 'standby-fib-snapshot', 'missing nfdc fib snapshot'))
        else:
            hops = exact_fib_hops(fib)
            if tfib_face and hops and hops[0] == tfib_face:
                checks.append(Check('PASS', 'exact-fib-agrees',
                                    f'first hop faceid={hops[0]} == tfib face'))
            else:
                checks.append(Check(
                    'FAIL', 'exact-fib-agrees',
                    f'tfib_face={tfib_face} fib_hops={hops}'))
        delivered_ev = find_event(events, 'service_after_standby')
        if delivered_ev and int(delivered_ev.get('after', 0)) > int(delivered_ev.get('before', 0)):
            checks.append(Check('PASS', 'service-after-standby',
                                f'before={delivered_ev["before"]} after={delivered_ev["after"]}'))
        else:
            delivered = 0 if consumer is None else len(
                re.findall(r'FRAME: delivered frame=', consumer))
            if delivered_ev:
                checks.append(Check(
                    'FAIL', 'service-after-standby',
                    f'no increase after Standby before={delivered_ev.get("before")} '
                    f'after={delivered_ev.get("after")}'))
            elif delivered > 0:
                checks.append(Check('FAIL', 'service-after-standby',
                                    'consumer has frames but no post-Standby before/after split'))
            else:
                checks.append(Check('FAIL', 'service-after-standby',
                                    'no FRAME: delivered frame= in consumer.log'))
    else:
        checks.append(Check('NOT_REACHED', 'tfib-standby',
                            'Standby not observed before poll budget; not claimed PASS'))

    if re.search(r'service-branch-events prefix=/LiveStream face=', r2):
        match = re.search(r'service-branch-events prefix=/LiveStream face=\S+', r2)
        checks.append(Check('PASS', 'service-branch', match.group(0) if match else 'observed'))
    else:
        checks.append(Check('FAIL', 'service-branch',
                            'missing service-branch-events prefix=/LiveStream face='))
    return checks


def validate_cf(results: str) -> List[Check]:
    checks: List[Check] = []
    params_ok(results, 'CF', checks)
    events = require_events(results, checks)
    required_files(results, [
        'producer.log', 'consumer.log', 'optoflood_producer.log',
        'optoflood_consumer.log',
        os.path.join('nfdc', 'help_route_add.txt'),
        os.path.join('nfdc', 'help_route_remove.txt'),
        os.path.join('nfdc', 'commands_used.txt'),
        os.path.join('logs', 'r2_nlsr.log'),
    ], checks)
    r2 = nfd_log(results, 'r2', checks)
    consumer = must_read(results, 'consumer.log', checks)
    if r2 is None:
        return checks
    check_no_proof_retire(r2, checks)

    if find_event(events, 'cf_prereq_standby_missing') or not re.search(
            r'OptoFlood tfib-standby prefix=/LiveStream reason=fib-agrees', r2):
        checks.append(Check('INCONCLUSIVE', 'cf-standby-prereq',
                            'r2 did not reach tfib-standby; CF not executed as specified'))
        return checks
    checks.append(Check('PASS', 'cf-standby-prereq', 'tfib-standby observed'))

    frozen = find_event(events, 'frozen_tfib_face') or find_event(events, 'tfib_update')
    tfib_face = None if frozen is None else str(frozen.get('face') or '')
    if not tfib_face:
        updates = parse_tfib_updates(r2)
        if updates:
            tfib_face = updates[-1][1]
    if not tfib_face:
        checks.append(Check('FAIL', 'frozen-tfib-face', 'no TFIB face id'))
        return checks
    checks.append(Check('PASS', 'frozen-tfib-face', tfib_face))

    incoming = list(re.finditer(
        rf'onIncomingInterest in=\(?({tfib_face})(?:,|\)|\s) interest={re.escape(PROBE_NAME)}'
        rf'\s+nonce=({NONCE_HEX})',
        r2,
    ))
    if not incoming:
        incoming = list(re.finditer(
            rf'onIncomingInterest in=\(?(\d+)(?:,|\)|\s) interest={re.escape(PROBE_NAME)}'
            rf'\s+nonce=({NONCE_HEX})',
            r2,
        ))
    if not incoming:
        checks.append(Check('FAIL', 'phase-f-ingress',
                            f'no onIncomingInterest for {PROBE_NAME} on r2'))
        return checks
    ingress = incoming[0].group(1).split(':')[0]
    nonce = incoming[0].group(2)
    checks.append(Check('PASS', 'phase-f-ingress',
                        f'in={ingress} nonce={nonce} name={PROBE_NAME}'))
    if ingress != tfib_face:
        checks.append(Check('FAIL', 'phase-f-tfib-ingress',
                            f'probe ingress={ingress} != tfib_face={tfib_face}'))
    else:
        checks.append(Check('PASS', 'phase-f-tfib-ingress',
                            f'probe entered r2 on TFIB face {tfib_face}'))

    any_probe_use = re.search(
        rf'OptoFlood tfib-forward interest={re.escape(PROBE_NAME)}',
        r2,
    )
    same_out_n = False
    for match in re.finditer(
            rf'onOutgoingInterest out={tfib_face} interest={re.escape(PROBE_NAME)}'
            rf'\s+nonce=({NONCE_HEX})\b',
            r2):
        if nonce_eq(match.group(1), nonce):
            same_out_n = True
            break
    if any_probe_use or same_out_n:
        checks.append(Check(
            'FAIL', 'phase-f-direct-tfib-use',
            f'forbidden probe TFIB Use or same-nonce N={nonce} out to ingress '
            f'fwd={bool(any_probe_use)} out={same_out_n}'))
    else:
        checks.append(Check('PASS', 'phase-f-direct-tfib-use',
                            f'no TFIB Use of {PROBE_NAME}; no same-nonce N={nonce} out={tfib_face}'))

    f_end = find_event(events, 'phase_f_end')
    fallback_during_f = bool(f_end and f_end.get('fallback_seen'))
    if fallback_during_f:
        checks.append(Check('FAIL', 'phase-f-no-fallback',
                            'probe caused tfib-fallback'))
    else:
        checks.append(Check('PASS', 'phase-f-no-fallback',
                            'probe did not reactivate Standby'))

    ingress_flood = re.search(
        rf'OptoFlood tfib-ingress flood interest={re.escape(PROBE_NAME)}',
        r2,
    )
    if ingress_flood:
        checks.append(Check(
            'FAIL', 'phase-f-tfib-ingress-flood',
            'tfib-ingress flood is the Active TFIB special path; not allowed in Standby Phase F'))
    else:
        checks.append(Check('PASS', 'phase-f-tfib-ingress-flood',
                            'no Active tfib-ingress flood for the probe'))

    strategy = re.search(
        rf'OptoFlood strategy flood interest={re.escape(PROBE_NAME)}\s+nonce=({NONCE_HEX})',
        r2,
    )
    hop_fwd = re.search(
        rf'OptoFlood forward interest={re.escape(PROBE_NAME)}\s+nonce=({NONCE_HEX}).*hopLimit=3',
        r2,
    )
    if strategy:
        nprime = strategy.group(1)
        if nonce_eq(nprime, nonce):
            checks.append(Check('FAIL', 'phase-f-allowed-flood',
                                f'strategy flood nonce {nprime} equals original N={nonce}'))
        elif hop_fwd and not nonce_eq(hop_fwd.group(1), nprime):
            checks.append(Check(
                'FAIL', 'phase-f-allowed-flood',
                f'strategy flood N\'={nprime} but hopLimit=3 nonce={hop_fwd.group(1)}'))
        elif hop_fwd:
            checks.append(Check(
                'PASS', 'phase-f-allowed-flood',
                f'strategy flood N\'={nprime} != N={nonce} then hopLimit=3'))
        else:
            checks.append(Check(
                'PASS', 'phase-f-allowed-flood',
                f'strategy flood N\'={nprime} != N={nonce} (no eligible hopLimit=3 outFace)'))
    elif hop_fwd:
        checks.append(Check(
            'FAIL', 'phase-f-allowed-flood',
            'hopLimit=3 forward without strategy flood; cannot treat as Standby BestRoute recovery'))
    else:
        checks.append(Check('PASS', 'phase-f-allowed-flood',
                            'no outgoing recovery packet; permitted after Standby skipped onUse'))

    remove_show = read_text(os.path.join(
        results, 'nfdc', 'r2_after_route_remove_route_show_livestream.txt'))
    fib_after = read_text(os.path.join(
        results, 'nfdc', 'r2_after_route_remove_fib.txt'))
    face_after = read_text(os.path.join(
        results, 'nfdc', 'r2_after_route_remove_face.txt'))
    if remove_show is None:
        checks.append(Check('FAIL', 'phase-c-route-snapshot', 'missing route show after remove'))
    else:
        leftover = parse_nlsr_hops(remove_show)
        if leftover:
            checks.append(Check('FAIL', 'phase-c-nlsr-removed',
                                f'origin=nlsr hops remain {leftover}'))
        else:
            checks.append(Check('PASS', 'phase-c-nlsr-removed',
                                'no origin=nlsr /LiveStream route'))
    if fib_after is None:
        checks.append(Check('FAIL', 'phase-c-fib-snapshot', 'missing fib list after remove'))
    else:
        hops = exact_fib_hops(fib_after)
        if not hops:
            checks.append(Check('PASS', 'phase-c-fib-unusable',
                                'exact /LiveStream FIB has no nexthops'))
        elif hops[0] != tfib_face:
            checks.append(Check('PASS', 'phase-c-fib-disagrees',
                                f'first hop {hops[0]} != tfib {tfib_face}'))
        else:
            checks.append(Check('FAIL', 'phase-c-fib-state',
                                f'exact FIB still agrees with TFIB face {tfib_face}'))
    if face_after is None:
        checks.append(Check('FAIL', 'phase-c-face-snapshot', 'missing face list after remove'))
    elif re.search(rf'faceid={tfib_face}\b', face_after):
        checks.append(Check('PASS', 'phase-c-tfib-face-retained', f'faceid={tfib_face}'))
    else:
        checks.append(Check('FAIL', 'phase-c-tfib-face-retained',
                            f'TFIB face {tfib_face} missing after withdrawal'))

    fb_ev = find_event(events, 'tfib_fallback')
    fb = None
    if fb_ev and fb_ev.get('line'):
        fb = re.search(
            r'OptoFlood tfib-fallback prefix=/LiveStream reason=(fib-unusable|fib-disagrees)',
            fb_ev['line'],
        )
    if not fb_ev:
        checks.append(Check('FAIL', 'phase-c-fallback',
                            'missing post-withdrawal tfib_fallback event (not inferred from full log)'))
    elif fb:
        checks.append(Check('PASS', 'phase-c-fallback', fb.group(0)))
    else:
        checks.append(Check('FAIL', 'phase-c-fallback',
                            str(fb_ev)))

    fwd_ev = find_event(events, 'tfib_forward_after_c')
    if fwd_ev and fwd_ev.get('line') and PROBE_NAME not in fwd_ev['line']:
        checks.append(Check('PASS', 'phase-c-tfib-forward', fwd_ev['line']))
    else:
        checks.append(Check('FAIL', 'phase-c-tfib-forward',
                            'no post-withdrawal business tfib-forward event'))
    out_ev = find_event(events, 'outgoing_after_c')
    if out_ev and out_ev.get('line') and tfib_face in out_ev['line']:
        checks.append(Check('PASS', 'phase-c-outgoing', out_ev['line']))
    elif tfib_face and out_ev:
        checks.append(Check('FAIL', 'phase-c-outgoing', out_ev.get('line', '')))
    else:
        checks.append(Check('FAIL', 'phase-c-outgoing',
                            f'no post-withdrawal onOutgoingInterest out={tfib_face}'))

    after_ev = find_event(events, 'consumer_delivered')
    if after_ev and int(after_ev.get('after', 0)) > int(after_ev.get('before', 0)):
        checks.append(Check('PASS', 'phase-c-service',
                            f'delivered before={after_ev["before"]} after={after_ev["after"]}'))
    else:
        checks.append(Check('FAIL', 'phase-c-service',
                            'no post-fallback consumer FRAME increase'))
    return checks


def validate_r(results: str) -> List[Check]:
    checks: List[Check] = []
    params_ok(results, 'R', checks)
    events = require_events(results, checks)
    required_files(results, [
        'producer.log', 'consumer.log', 'optoflood_consumer.log',
        os.path.join('logs', 'r2_nfd.log'),
        os.path.join('logs', 'r4_nfd.log'),
        os.path.join('logs', 'r5_nfd.log'),
        os.path.join('logs', 'r3_nlsr.log'),
        os.path.join('nfdc', 'r3_pre_mobility_face.txt'),
    ], checks)
    r3 = nfd_log(results, 'r3', checks)
    daemon = must_read(results, 'optoflood_producer.log', checks)
    if r3 is None:
        return checks
    check_no_proof_retire(r3, checks)

    map_ev = find_event(events, 'r3_face_map')
    r3_to_r4 = None if map_ev is None else map_ev.get('r3_to_r4')
    r3_to_r5 = None if map_ev is None else map_ev.get('r3_to_r5')
    if not r3_to_r4 or not r3_to_r5:
        checks.append(Check('FAIL', 'r3-face-map', f'{map_ev}'))
        return checks
    checks.append(Check('PASS', 'r3-face-map',
                        f'r3_to_r4={r3_to_r4} r3_to_r5={r3_to_r5}'))

    s1_ev = find_event(events, 's1_tfib_update')
    s2_ev = find_event(events, 's2_tfib_update')
    updates = parse_tfib_updates(r3)
    s1_seq = s1_ev.get('seq') if s1_ev else None
    s1_face = s1_ev.get('face') if s1_ev else None
    s2_seq = s2_ev.get('seq') if s2_ev else None
    s2_face = s2_ev.get('face') if s2_ev else None
    if s1_seq is None:
        for prefix, face, seq in updates:
            if face == str(r3_to_r4):
                s1_seq, s1_face = seq, face
                break
    if s2_seq is None:
        best = None
        for prefix, face, seq in updates:
            if face == str(r3_to_r5) and (best is None or int(seq) > int(best)):
                s2_seq, s2_face, best = seq, face, seq
    if s1_seq is None or s1_face != str(r3_to_r4):
        checks.append(Check('FAIL', 's1-generation',
                            f'need TFIB update face={r3_to_r4}; got face={s1_face} seq={s1_seq}'))
    else:
        checks.append(Check('PASS', 's1-generation',
                            f'face={s1_face} newFaceSeq={s1_seq}'))
    if s2_seq is None or s2_face != str(r3_to_r5):
        checks.append(Check('FAIL', 's2-generation',
                            f'need TFIB update face={r3_to_r5}; got face={s2_face} seq={s2_seq}'))
        return checks
    checks.append(Check('PASS', 's2-generation',
                        f'face={s2_face} newFaceSeq={s2_seq}'))
    try:
        if int(s2_seq) <= int(s1_seq or -1):
            checks.append(Check('FAIL', 'seq-increase', f'S1={s1_seq} S2={s2_seq}'))
        else:
            checks.append(Check('PASS', 'seq-increase', f'S2={s2_seq} > S1={s1_seq}'))
    except (TypeError, ValueError):
        checks.append(Check('FAIL', 'seq-increase', f'S1={s1_seq} S2={s2_seq}'))

    after_s2 = r3
    s2_pat = rf'TFIB update prefix=/LiveStream\s+face={re.escape(str(r3_to_r5))}\s+newFaceSeq={re.escape(str(s2_seq))}'
    s2_hits = list(re.finditer(s2_pat, r3))
    if s2_hits:
        after_s2 = r3[s2_hits[-1].start():]
    use_ok = False
    use_detail = 'missing S2 Use/out'
    for fwd in re.finditer(r'OptoFlood tfib-forward interest=(\S+)\s+nonce=(\d+)', after_s2):
        name, nonce = fwd.group(1), fwd.group(2)
        if name.startswith('/LiveStream/_') or PROBE_NAME in name:
            continue
        if not name.startswith('/LiveStream/'):
            continue
        if re.search(
                rf'onOutgoingInterest out={r3_to_r5} interest={re.escape(name)}\s+nonce={nonce}\b',
                after_s2):
            use_ok = True
            use_detail = f'tfib-forward + out={r3_to_r5} interest={name} nonce={nonce}'
            break
    if use_ok:
        checks.append(Check('PASS', 's2-forwarding-authority', use_detail))
    else:
        checks.append(Check('FAIL', 's2-forwarding-authority',
                            'TFIB update line is insufficient; missing S2 Use/out'))

    if daemon is not None:
        epochs = re.findall(r'MOBILITY: epoch=(\d+)', daemon)
        seqs = re.findall(r'NewFaceSeq=(\d+)', daemon)
        if len(epochs) >= 3:
            nums = [int(x) for x in epochs]
            if nums == sorted(nums) and len(set(nums)) == len(nums):
                checks.append(Check('PASS', 'daemon-epoch', f'epochs={nums}'))
            else:
                checks.append(Check('FAIL', 'daemon-epoch', f'epochs={nums}'))
        else:
            checks.append(Check('FAIL', 'daemon-epoch', f'epochs={epochs}'))
        if seqs:
            checks.append(Check('PASS', 'daemon-newfaceseq', f'NewFaceSeq={seqs}'))
        else:
            checks.append(Check('PASS', 'daemon-newfaceseq',
                                'absent (supporting only; TFIB seq is authoritative)'))

    later_updates = parse_tfib_updates(after_s2)
    higher = []
    obsolete = []
    for idx, (_prefix, face, seq) in enumerate(later_updates):
        if idx == 0 and face == str(r3_to_r5) and seq == str(s2_seq):
            continue
        try:
            nseq = int(seq)
            s2n = int(s2_seq)
        except (TypeError, ValueError):
            continue
        if nseq > s2n:
            higher.append((face, seq))
        elif face != str(r3_to_r5):
            obsolete.append((face, seq))
    if higher:
        checks.append(Check('FAIL', 'no-higher-generation',
                            f'accepted seq after S2={s2_seq}: {higher}'))
    else:
        checks.append(Check('PASS', 'no-higher-generation',
                            f'no TFIB update seq > S2={s2_seq}'))
    if obsolete:
        checks.append(Check(
            'FAIL', 's2-face-authority',
            f'update to non-S2 face without higher seq: {obsolete}'))
    else:
        checks.append(Check('PASS', 's2-face-authority',
                            f'S2 face {r3_to_r5} remained the accepted face'))

    def line_ts(pattern: str) -> Tuple[Optional[float], Optional[str]]:
        last_ts, last_line = None, None
        for raw in r3.splitlines():
            if re.search(pattern, raw):
                ts = parse_nfd_ts(raw)
                last_ts, last_line = ts, raw
        return last_ts, last_line

    s1_log_ts = None
    if s1_seq:
        s1_log_ts, _ = line_ts(
            rf'TFIB update prefix=/LiveStream\s+face={re.escape(str(r3_to_r4))}\s+newFaceSeq={re.escape(str(s1_seq))}'
        )
    s2_log_ts, s2_line = line_ts(s2_pat)
    retire_log_ts, retire_line = line_ts(
        r'OptoFlood tfib-retire prefix=/LiveStream reason=expired')
    s1_wall = s1_log_ts or (s1_ev or {}).get('log_ts') or (s1_ev or {}).get('seen_at') or (s1_ev or {}).get('wall')
    s2_wall = s2_log_ts or (s2_ev or {}).get('log_ts') or (s2_ev or {}).get('seen_at') or (s2_ev or {}).get('wall')
    retire_ev = find_event(events, 'tfib_retire')
    standby = find_event(events, 'tfib_standby') or re.search(
        r'OptoFlood tfib-standby prefix=/LiveStream reason=fib-agrees', r3)
    fb_after = (
        find_event(events, 's2_fallback_after_standby')
        or find_event(events, 'unexpected_fallback_after_standby')
    )
    fb_log = re.search(
        r'OptoFlood tfib-fallback prefix=/LiveStream reason=(fib-unusable|fib-disagrees)',
        after_s2,
    )
    fallback_after_standby = bool(standby and (fb_after or fb_log))

    post_fb_use = False
    post_fb_detail = 'no post-fallback S2 Use'
    if fallback_after_standby:
        after_fb = after_s2
        if fb_log:
            after_fb = after_s2[fb_log.start():]
        elif fb_after and fb_after.get('line'):
            pos = after_s2.find(str(fb_after['line']))
            if pos >= 0:
                after_fb = after_s2[pos:]
        for fwd in re.finditer(r'OptoFlood tfib-forward interest=(\S+)\s+nonce=(\d+)', after_fb):
            name, nonce = fwd.group(1), fwd.group(2)
            if name.startswith('/LiveStream/_') or PROBE_NAME in name:
                continue
            if not name.startswith('/LiveStream/'):
                continue
            if re.search(
                    rf'onOutgoingInterest out={r3_to_r5} interest={re.escape(name)}\s+nonce={nonce}\b',
                    after_fb):
                post_fb_use = True
                post_fb_detail = (
                    f'after fallback tfib-forward + out={r3_to_r5} '
                    f'interest={name} nonce={nonce}')
                break
        if not post_fb_use:
            ev = find_event(events, 's2_tfib_forward_after_fallback')
            out_ev = find_event(events, 's2_outgoing_after_fallback')
            if (ev and out_ev and
                    str(r3_to_r5) in str(out_ev.get('line', ''))):
                post_fb_use = True
                post_fb_detail = ev.get('line', post_fb_detail)
        if post_fb_use:
            checks.append(Check('PASS', 's2-post-fallback-forward', post_fb_detail))
        else:
            checks.append(Check(
                'FAIL', 's2-post-fallback-forward',
                'fallback after Standby without subsequent S2-face tfib-forward'))

    if s1_wall is not None and s2_wall is not None:
        old_deadline = float(s1_wall) + HARD_DEADLINE_S
        retire_at = retire_log_ts
        if retire_at is None and retire_ev:
            retire_at = float(retire_ev.get('seen_at') or retire_ev['wall'])
        s2_alive_after_old = True
        if retire_at is not None and retire_at <= old_deadline - HARD_DEADLINE_TOL_S:
            s2_alive_after_old = False
        if s2_alive_after_old and (use_ok or standby or post_fb_use):
            checks.append(Check('PASS', 'old-deadline-isolation',
                                f'S2 still alive after T1+120s (T1={s1_wall})'))
        else:
            checks.append(Check('FAIL', 'old-deadline-isolation',
                                f'retire_at={retire_at} old_deadline={old_deadline}'))

    if retire_log_ts is None and not retire_ev and not re.search(
            r'OptoFlood tfib-retire prefix=/LiveStream reason=expired', r3):
        checks.append(Check('FAIL', 'hard-deadline-retire',
                            'no tfib-retire reason=expired for /LiveStream'))
        return checks

    retire_at = retire_log_ts
    if retire_at is None and retire_ev:
        retire_at = float(retire_ev.get('seen_at') or retire_ev['wall'])
    if s2_wall is None:
        checks.append(Check('FAIL', 'hard-deadline-dt', 'missing T_insert_final'))
        return checks
    if retire_at is None:
        checks.append(Check('FAIL', 'hard-deadline-dt', 'missing retire timestamp'))
        return checks
    delta = retire_at - float(s2_wall)
    checks.append(Check('PASS', 'hard-deadline-dt',
                        f'T_insert_final={s2_wall} T_retire={retire_at} dt={delta:.3f}s'
                        f' line={s2_line or ""}'))
    near = abs(delta - HARD_DEADLINE_S) <= HARD_DEADLINE_TOL_S
    if not near:
        checks.append(Check('FAIL', 'hard-deadline-window',
                            f'dt={delta:.3f}s not within 120s ±{HARD_DEADLINE_TOL_S}s'))
    elif fallback_after_standby:
        if post_fb_use and not higher and not obsolete:
            checks.append(Check(
                'PASS', 'HARD_DEADLINE_ACTIVE_CAP_PASS',
                f'S2 Standby then fallback then Active Use; expire dt={delta:.3f}s; '
                'not claimed as Standby hardDeadline'))
        else:
            checks.append(Check(
                'FAIL', 'hard-deadline-mode',
                'Standby fallback without sufficient same-generation Active evidence'))
    elif standby:
        checks.append(Check('PASS', 'HARD_DEADLINE_STANDBY_PASS',
                            f'S2 Standby then expire dt={delta:.3f}s'))
    else:
        forwards = list(re.finditer(
            r'OptoFlood tfib-forward interest=/LiveStream/', after_s2))
        if len(forwards) >= 2:
            checks.append(Check(
                'PASS', 'HARD_DEADLINE_ACTIVE_CAP_PASS',
                f'S2 remained Active with repeated tfib-forward n={len(forwards)}; '
                f'expire dt={delta:.3f}s; not claimed as Standby hardDeadline'))
        else:
            checks.append(Check(
                'FAIL', 'hard-deadline-mode',
                'no Standby and insufficient continued tfib-forward to distinguish idle 5s'))
    return checks


def overall(checks: List[Check]) -> int:
    print_checks(checks)
    if any(c.status == 'FAIL' for c in checks):
        print('OVERALL: FAIL')
        return 1
    if any(c.status == 'INCONCLUSIVE' for c in checks):
        print('OVERALL: INCONCLUSIVE')
        return 2
    not_reached = [c.name for c in checks if c.status == 'NOT_REACHED']
    if not_reached:
        print('OVERALL: PASS_WITH_NOT_REACHED ' + ','.join(not_reached))
        return 0
    print('OVERALL: PASS')
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print('usage: python3 validate_r2.py A|CF|R <results-dir>', file=sys.stderr)
        return 2
    cell = sys.argv[1].strip().upper()
    results = os.path.abspath(sys.argv[2])
    if cell not in ('A', 'CF', 'R'):
        print('cell must be A, CF, or R', file=sys.stderr)
        return 2
    if not os.path.isdir(results):
        print(f'FAIL: results dir missing: {results}')
        return 1
    if cell == 'A':
        checks = validate_a(results)
    elif cell == 'CF':
        checks = validate_cf(results)
    else:
        checks = validate_r(results)
    verdict_path = os.path.join(results, 'validator_output.txt')
    code = overall(checks)
    with open(verdict_path, 'w', encoding='utf-8') as handle:
        for check in checks:
            handle.write(check.line() + '\n')
        if any(c.status == 'FAIL' for c in checks):
            handle.write('OVERALL: FAIL\n')
        elif any(c.status == 'INCONCLUSIVE' for c in checks):
            handle.write('OVERALL: INCONCLUSIVE\n')
        elif any(c.status == 'NOT_REACHED' for c in checks):
            handle.write('OVERALL: PASS_WITH_NOT_REACHED\n')
        else:
            handle.write('OVERALL: PASS\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
