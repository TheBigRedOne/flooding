#!/usr/bin/env python3
"""Pure-R2 TFIB runtime-gate Mini-NDN driver.

Independent of test/exp_test.py. One cell per process. Requires root/Mini-NDN.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from shlex import quote
from time import sleep
from typing import Any, Dict, List, Optional, Tuple

from mininet.log import info, setLogLevel
from mininet.topo import Topo
from minindn.apps.app_manager import AppManager
from minindn.apps.nfd import Nfd
from minindn.apps.nlsr import Nlsr
from minindn.minindn import Minindn

REQUIRED_NFD_VERSION = os.getenv('R2_REQUIRED_NFD_VERSION', '24.07+git.56b8d8db')
NLSR_INFOEDIT = [
    ('neighbors.event-driven-adjacency-verification', 'off'),
    ('neighbors.result-driven-adj-lsa-build', 'off'),
    ('neighbors.corridor-prioritised-routing', 'off'),
]
STANDBY_POLL_MAX_S = 180.0
STANDBY_AFTER_INSERT_S = 110.0
HARD_DEADLINE_WAIT_S = 125.0
RAPID_GAP_S = 2.0
WARMUP_NLSR_S = 30
WARMUP_APP_S = 60
PROBE_NAME = '/LiveStream/_r2probe'


class TunableNlsr(Nlsr):
    """Apply infoedit changes after Mini-NDN writes nlsr.conf, before start."""

    def __init__(self, node, infoeditChanges=None, **kwargs):
        super().__init__(node, **kwargs)
        self._apply_manual_infoedit_changes(infoeditChanges)

    def _apply_manual_infoedit_changes(self, infoedit_changes):
        if not infoedit_changes:
            return
        conf_dir = getattr(self, 'homeDir', self.node.params['params']['homeDir'])
        conf_file = getattr(self, 'confFile', os.path.join(conf_dir, 'nlsr.conf'))
        for key, value in infoedit_changes:
            self.node.cmd(
                f'cd {quote(conf_dir)} && '
                f'infoedit -f {quote(os.path.basename(conf_file))} -s {quote(key)} -v {quote(value)}'
            )


class BranchTopo(Topo):
    """R1–R2–R3–R4 chain with r3–r5 branch. Same as test/exp_test.py."""

    def build(self):
        r1 = self.addHost('r1')
        r2 = self.addHost('r2')
        r3 = self.addHost('r3')
        r4 = self.addHost('r4')
        r5 = self.addHost('r5')
        consumer = self.addHost('consumer')
        producer = self.addHost('producer')
        self.addLink(r1, r2, bw=1000, delay='1ms')
        self.addLink(r2, r3, bw=1000, delay='1ms')
        self.addLink(r3, r4, bw=1000, delay='1ms')
        self.addLink(r3, r5, bw=1000, delay='1ms')
        self.addLink(consumer, r1, bw=100, delay='5ms')
        self.addLink(producer, r2, bw=100, delay='5ms')
        self.addLink(producer, r3, bw=100, delay='5ms')
        self.addLink(producer, r4, bw=100, delay='5ms')
        self.addLink(producer, r5, bw=100, delay='5ms')


def home_dir(node) -> str:
    return node.params['params']['homeDir']


def nfd_log_path(node) -> str:
    return os.path.join(home_dir(node), 'log', 'nfd.log')


def nlsr_log_path(node) -> str:
    return os.path.join(home_dir(node), 'log', 'nlsr.log')


def wall() -> float:
    return time.time()


class CellRun:
    def __init__(self, cell: str, experiment_dir: str, results_dir: str):
        self.cell = cell
        self.experiment_dir = experiment_dir
        self.results_dir = results_dir
        self.events: List[Dict[str, Any]] = []
        os.makedirs(results_dir, exist_ok=True)
        for sub in ('logs', 'snapshots', 'pcap', 'nfdc'):
            os.makedirs(os.path.join(results_dir, sub), exist_ok=True)

    def event(self, name: str, **fields: Any) -> None:
        rec = {'event': name, 'wall': wall()}
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                rec[key] = value
            else:
                rec[key] = str(value)
        self.events.append(rec)
        path = os.path.join(self.results_dir, 'events.jsonl')
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(rec, ensure_ascii=True) + '\n')
        info(f'R2 event {name} {fields}\n')

    def write_text(self, relpath: str, text: str) -> str:
        path = os.path.join(self.results_dir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text if text.endswith('\n') or text == '' else text + '\n')
        return path

    def node_capture(self, node, relpath: str, command: str) -> str:
        path = os.path.join(self.results_dir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        node.cmd(f'{command} > {quote(path)} 2>&1 || true')
        return path

    def save_nfdc(self, node, label: str) -> None:
        base = f'nfdc/{node.name}_{label}'
        self.node_capture(node, f'{base}_face.txt', 'nfdc face list')
        self.node_capture(node, f'{base}_fib.txt', 'nfdc fib list')
        self.node_capture(node, f'{base}_route_show_livestream.txt',
                          'nfdc route show prefix /LiveStream')
        self.node_capture(node, f'{base}_route_list.txt', 'nfdc route list')

    def copy_full_logs(self, nodes) -> None:
        for node in nodes:
            src_nfd = nfd_log_path(node)
            src_nlsr = nlsr_log_path(node)
            node.cmd(
                f'cp -f {quote(src_nfd)} {quote(os.path.join(self.results_dir, "logs", node.name + "_nfd.log"))} '
                f'2>/dev/null || true'
            )
            node.cmd(
                f'cp -f {quote(src_nlsr)} {quote(os.path.join(self.results_dir, "logs", node.name + "_nlsr.log"))} '
                f'2>/dev/null || true'
            )


def parse_face_list(text: str) -> List[Dict[str, str]]:
    faces: List[Dict[str, str]] = []
    for line in text.splitlines():
        match_id = re.search(r'faceid=(\d+)', line)
        if not match_id:
            continue
        match_remote = re.search(r'remote=(\S+)', line)
        faces.append({
            'id': match_id.group(1),
            'remote': match_remote.group(1) if match_remote else '',
            'raw': line.strip(),
        })
    return faces


def face_id_toward(local_node, remote_node, face_text: str) -> Optional[str]:
    connections = local_node.connectionsTo(remote_node)
    if not connections:
        return None
    _local_intf, remote_intf = connections[0]
    ip = remote_intf.IP()
    if not ip:
        return None
    for face in parse_face_list(face_text):
        if ip in face['remote']:
            return face['id']
    return None


def read_file(path: str) -> str:
    if not os.path.exists(path):
        return ''
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.read()


def grep_node_log(node, pattern: str, log='nfd') -> str:
    path = nfd_log_path(node) if log == 'nfd' else nlsr_log_path(node)
    return node.cmd(f'grep -E {quote(pattern)} {quote(path)} 2>/dev/null || true')


def log_bytes(node) -> int:
    out = node.cmd(f'wc -c < {quote(nfd_log_path(node))} 2>/dev/null || echo 0').strip()
    token = out.split()[0] if out else '0'
    try:
        return int(token)
    except ValueError:
        return 0


def grep_since(node, pattern: str, offset: int) -> str:
    path = nfd_log_path(node)
    return node.cmd(
        f'tail -c +{int(offset) + 1} {quote(path)} 2>/dev/null | '
        f'grep -E {quote(pattern)} || true'
    )


def poll_grep_since(node, pattern: str, offset: int, timeout_s: float,
                    interval_s: float = 0.25) -> Tuple[Optional[str], float]:
    deadline = wall() + timeout_s
    while wall() < deadline:
        text = grep_since(node, pattern, offset)
        if text.strip():
            return text, wall()
        sleep(interval_s)
    return None, wall()


def poll_grep(node, pattern: str, timeout_s: float, interval_s: float = 0.25,
              log='nfd') -> Tuple[Optional[str], float]:
    deadline = wall() + timeout_s
    while wall() < deadline:
        text = grep_node_log(node, pattern, log=log)
        if text.strip():
            return text, wall()
        sleep(interval_s)
    return None, wall()


def line_containing(text: str, match: re.Match) -> str:
    start = text.rfind('\n', 0, match.start()) + 1
    end = text.find('\n', match.end())
    if end < 0:
        end = len(text)
    return text[start:end]


def parse_nfd_ts(line: str) -> Optional[float]:
    match = re.match(r'^(\d+)\.(\d{6})\b', line.strip())
    if not match:
        return None
    return float(match.group(1)) + float(match.group(2)) / 1_000_000.0


def _tfib_update_fields(match: re.Match) -> Dict[str, Any]:
    full = line_containing(match.string, match)
    fields: Dict[str, Any] = {
        'prefix': match.group(1),
        'face': match.group(2),
        'seq': match.group(3),
        'line': full.strip(),
    }
    ts = parse_nfd_ts(full)
    if ts is not None:
        fields['log_ts'] = ts
    return fields


def last_tfib_update(text: str) -> Optional[Dict[str, Any]]:
    matches = list(re.finditer(
        r'TFIB update prefix=(/LiveStream)\s+face=(\d+)\s+newFaceSeq=(\d+)',
        text,
    ))
    if not matches:
        return None
    return _tfib_update_fields(matches[-1])


def first_tfib_update_for_face(text: str, face_id: str) -> Optional[Dict[str, Any]]:
    for match in re.finditer(
        r'TFIB update prefix=(/LiveStream)\s+face=(\d+)\s+newFaceSeq=(\d+)',
        text,
    ):
        if match.group(2) == str(face_id):
            return _tfib_update_fields(match)
    return None


def highest_tfib_update_for_face(text: str, face_id: str) -> Optional[Dict[str, Any]]:
    found: Optional[Dict[str, Any]] = None
    for match in re.finditer(
        r'TFIB update prefix=(/LiveStream)\s+face=(\d+)\s+newFaceSeq=(\d+)',
        text,
    ):
        if match.group(2) != str(face_id):
            continue
        cand = _tfib_update_fields(match)
        if found is None or int(cand['seq']) >= int(found['seq']):
            found = cand
    return found


def parse_nlsr_nexthops(route_show: str) -> List[str]:
    hops: List[str] = []
    for match in re.finditer(
            r'nexthop=(\d+)\s+origin=(?:nlsr|128)\b',
            route_show,
            flags=re.IGNORECASE):
        hops.append(match.group(1))
    return hops


def exact_fib_hops(fib_text: str, prefix: str = '/LiveStream') -> List[str]:
    for line in fib_text.splitlines():
        stripped = line.strip()
        if re.match(rf'^{re.escape(prefix)}\s+nexthops=', stripped):
            return re.findall(r'faceid=(\d+)', stripped)
    return []


def count_delivered(consumer_log: str) -> int:
    return len(re.findall(r'FRAME: delivered frame=', consumer_log))


def start_common(run: CellRun):
    nfd_version = os.popen('nfd --version').read().strip()
    run.write_text('nfd_version.txt', nfd_version + '\n')
    if nfd_version != REQUIRED_NFD_VERSION:
        run.event('nfd_version_mismatch', actual=nfd_version, required=REQUIRED_NFD_VERSION)
        raise SystemExit(
            f'FAIL: nfd --version {nfd_version!r} != {REQUIRED_NFD_VERSION!r}'
        )

    params = [
        f'cell={run.cell}',
        f'nfd.version={REQUIRED_NFD_VERSION}',
    ]
    params.extend(f'{key}={value}' for key, value in NLSR_INFOEDIT)
    params.append('OPTOFLOOD_NLSR_VERIFY_NOW=unset')
    run.write_text('params.txt', '\n'.join(params) + '\n')

    Minindn.cleanUp()
    Minindn.verifyDependencies()
    ndn = Minindn(topo=BranchTopo())
    ndn.start()
    info('Starting NFD on all nodes\n')
    AppManager(ndn, ndn.net.hosts, Nfd, logLevel='DEBUG')
    info('Starting NLSR on all nodes\n')
    nlsrs = AppManager(ndn, ndn.net.hosts, TunableNlsr, logLevel='DEBUG',
                       infoeditChanges=NLSR_INFOEDIT)
    sleep(WARMUP_NLSR_S)
    switch_re = (
        'event-driven-adjacency-verification|'
        'result-driven-adj-lsa-build|'
        'corridor-prioritised-routing'
    )
    for name in ('r1', 'r2', 'r3', 'r4', 'r5'):
        node = ndn.net[name]
        conf = os.path.join(home_dir(node), 'nlsr.conf')
        dump = node.cmd(
            f'grep -E {quote(switch_re)} {quote(conf)} 2>/dev/null || true'
        )
        run.write_text(f'logs/{name}_nlsr_switches.txt', dump)

    ndn.net.configLinkStatus('producer', 'r3', 'down')
    ndn.net.configLinkStatus('producer', 'r4', 'down')
    ndn.net.configLinkStatus('producer', 'r5', 'down')

    nodes = {name: ndn.net[name]
             for name in ('r1', 'r2', 'r3', 'r4', 'r5', 'producer', 'consumer')}
    producer = nodes['producer']
    consumer = nodes['consumer']

    producer.cmd('ndnsec key-gen /LiveStream >/dev/null 2>&1')
    producer.cmd(
        'ndnsec cert-dump -i /LiveStream > '
        '/home/vagrant/flooding/experiment/app/livestream-trust-anchor.cert'
    )
    producer.cmd('ndnsec key-gen -n /localhost/optoflood >/dev/null 2>&1')

    pcap_dir = os.path.join(run.results_dir, 'pcap')
    for name, node in nodes.items():
        pcap = os.path.join(pcap_dir, f'{name}.pcap')
        node.cmd(
            f'tcpdump -i any -U -w {quote(pcap)} '
            f'&> {quote(os.path.join(run.results_dir, "tcpdump_" + name + ".log"))} &'
        )

    producer_exec = os.path.join(run.experiment_dir, 'producer')
    consumer_exec = os.path.join(run.experiment_dir, 'consumer')
    daemon_exec = os.path.join(run.experiment_dir, 'optoflood-daemon')
    producer.cmd(f'{quote(producer_exec)} &> {quote(os.path.join(run.results_dir, "producer.log"))} &')
    consumer.cmd(f'{quote(consumer_exec)} &> {quote(os.path.join(run.results_dir, "consumer.log"))} &')
    daemon_env = 'GUARD_PREFIX=/LiveStream EXP_GUARD_INTERVAL_MS=1000'
    producer.cmd(
        f'{daemon_env} {quote(daemon_exec)} producer '
        f'&> {quote(os.path.join(run.results_dir, "optoflood_producer.log"))} &'
    )
    consumer.cmd(
        f'{daemon_env} {quote(daemon_exec)} consumer '
        f'&> {quote(os.path.join(run.results_dir, "optoflood_consumer.log"))} &'
    )
    sleep(WARMUP_APP_S)
    for name in ('r1', 'r2', 'r3', 'r4', 'r5'):
        run.save_nfdc(nodes[name], 'T0')
    run.event('warmup_complete')
    return ndn, nlsrs, nodes


def stop_tcpdump(nodes) -> None:
    for node in nodes.values():
        node.cmd("pkill -f 'tcpdump -i any' || true")


def teardown(run: CellRun, ndn, nodes) -> None:
    stop_tcpdump(nodes)
    sleep(1.5)
    run.copy_full_logs(nodes.values())
    ndn.stop()


def handoff(ndn, run: CellRun, current: str, nxt: str) -> None:
    info(f'Handoff producer {current} -> {nxt}\n')
    ndn.net.configLinkStatus('producer', current, 'down')
    ndn.net.configLinkStatus('producer', nxt, 'up')
    run.event('handoff', src=current, dst=nxt)


def wait_standby(run: CellRun, node, insert_wall: Optional[float]) -> Optional[str]:
    remaining_insert = STANDBY_AFTER_INSERT_S
    if insert_wall is not None:
        remaining_insert = max(0.0, insert_wall + STANDBY_AFTER_INSERT_S - wall())
    timeout = min(STANDBY_POLL_MAX_S, remaining_insert if insert_wall else STANDBY_POLL_MAX_S)
    run.event('standby_poll_begin', timeout_s=timeout, insert_wall=insert_wall)
    text, seen_at = poll_grep(
        node,
        r'OptoFlood tfib-standby prefix=/LiveStream reason=fib-agrees',
        timeout,
    )
    if text and text.strip():
        run.event('tfib_standby', seen_at=seen_at, line=text.strip().splitlines()[-1])
        return text
    run.event('tfib_standby_not_reached', waited_s=timeout)
    return None


def cell_a(run: CellRun) -> int:
    ndn, _nlsrs, nodes = start_common(run)
    r2 = nodes['r2']
    try:
        handoff(ndn, run, 'r2', 'r3')
        update_text, _ = poll_grep(
            r2, r'OptoFlood TFIB update prefix=/LiveStream', 30.0)
        parsed = last_tfib_update(update_text or '')
        if parsed:
            run.event('tfib_update', **parsed)
            insert_wall = parsed.get('log_ts', wall())
        else:
            run.event('tfib_update_missing')
            insert_wall = None
        if insert_wall is not None:
            forward_text, _ = poll_grep(r2, r'OptoFlood tfib-forward interest=', 20.0)
            if forward_text and forward_text.strip():
                run.event('tfib_forward', line=forward_text.strip().splitlines()[-1])
            standby = wait_standby(run, r2, insert_wall)
            run.save_nfdc(r2, 'standby' if standby else 'standby_timeout')
            before = count_delivered(read_file(os.path.join(run.results_dir, 'consumer.log')))
            sleep(5)
            after = count_delivered(read_file(os.path.join(run.results_dir, 'consumer.log')))
            run.event('service_after_standby', before=before, after=after, standby=bool(standby))
        else:
            run.save_nfdc(r2, 'no_tfib')
        run.event(
            'consumer_delivered_after_wait',
            count=count_delivered(read_file(os.path.join(run.results_dir, 'consumer.log'))),
        )
        sb, _ = poll_grep(r2, r'service-branch-events prefix=/LiveStream', 5.0)
        if not (sb and sb.strip()):
            sb = grep_node_log(r2, r'service-branch-events prefix=/LiveStream')
        if sb and sb.strip():
            run.event('service_branch', line=sb.strip().splitlines()[-1])
        return 0
    finally:
        teardown(run, ndn, nodes)


def cell_cf(run: CellRun) -> int:
    ndn, nlsrs, nodes = start_common(run)
    r2 = nodes['r2']
    r3 = nodes['r3']
    try:
        help_add = r2.cmd('nfdc route add --help 2>&1 || true')
        help_remove = r2.cmd('nfdc route remove --help 2>&1 || true')
        help_route = r2.cmd('nfdc help route 2>&1 || true')
        run.write_text('nfdc/help_route_add.txt', help_add)
        run.write_text('nfdc/help_route_remove.txt', help_remove)
        run.write_text('nfdc/help_route.txt', help_route)
        run.write_text(
            'nfdc/commands_used.txt',
            '\n'.join([
                '# Grammar basis: NFD tools/nfdc/rib-module.cpp + docs/manpages/nfdc-route.rst',
                '# Default origin for add/remove is static (255). NLSR origin is nlsr (128).',
                '# Runtime preflight saved in help_route*.txt; commands below are named-argument form.',
                'nfdc route add prefix /LiveStream/_r2probe nexthop <R3_FACE_TO_R2> origin static cost 0',
                'nfdc route remove prefix /LiveStream/_r2probe nexthop <R3_FACE_TO_R2> origin static',
                'nfdc route remove prefix /LiveStream nexthop <FACEID> origin nlsr',
                'nfdc route show prefix /LiveStream',
                'nfdc face list',
                'nfdc fib list',
                '',
            ]),
        )

        handoff(ndn, run, 'r2', 'r3')
        update_text, _ = poll_grep(r2, r'OptoFlood TFIB update prefix=/LiveStream', 30.0)
        parsed = last_tfib_update(update_text or '')
        if not parsed:
            run.event('tfib_update_missing')
            return 2
        tfib_face = parsed['face']
        run.event('tfib_update', **parsed)
        insert_wall = parsed.get('log_ts', wall())
        standby = wait_standby(run, r2, insert_wall if isinstance(insert_wall, float) else wall())
        if not standby:
            run.event('cf_prereq_standby_missing')
            run.save_nfdc(r2, 'standby_timeout')
            return 2
        offset_after_standby = log_bytes(r2)
        run.event('standby_log_offset', offset=offset_after_standby)
        run.save_nfdc(r2, 'pre_f')
        face_r2 = read_file(os.path.join(run.results_dir, 'nfdc', 'r2_pre_f_face.txt'))
        run.event('frozen_tfib_face', face=tfib_face, mapping=[
            f for f in parse_face_list(face_r2) if f['id'] == tfib_face
        ])

        r3.cmd('nfdc face list > ' + quote(os.path.join(run.results_dir, 'nfdc', 'r3_pre_f_face.txt')))
        face_r3 = read_file(os.path.join(run.results_dir, 'nfdc', 'r3_pre_f_face.txt'))
        r3_to_r2 = face_id_toward(r3, r2, face_r3)
        run.event('r3_face_to_r2', face=r3_to_r2)
        if not r3_to_r2:
            run.event('r3_face_to_r2_missing')
            return 1

        peek_bin = r3.cmd('command -v ndnpeek || true').strip()
        run.write_text('nfdc/ndnpeek_path.txt', peek_bin + '\n')
        if not peek_bin:
            run.event('ndnpeek_missing')
            return 1

        add_cmd = (
            f'nfdc route add prefix {PROBE_NAME} nexthop {r3_to_r2} origin static cost 0'
        )
        add_out = r3.cmd(add_cmd)
        run.write_text('nfdc/r3_probe_route_add.txt', add_cmd + '\n' + add_out)
        run.event('phase_f_start', add_cmd=add_cmd, add_out=add_out.strip())
        peek_out = r3.cmd(f'ndnpeek -w 1000 {PROBE_NAME}')
        run.write_text('nfdc/r3_ndnpeek_probe.txt', peek_out)
        sleep(1)
        fb_f = grep_since(r2, r'OptoFlood tfib-fallback prefix=/LiveStream', offset_after_standby)
        fallback_during_f = bool(fb_f.strip())
        run.event('phase_f_end', fallback_seen=fallback_during_f,
                  fallback_line=fb_f.strip().splitlines()[-1] if fb_f.strip() else '')
        run.save_nfdc(r2, 'after_f')
        remove_cmd = (
            f'nfdc route remove prefix {PROBE_NAME} nexthop {r3_to_r2} origin static'
        )
        remove_out = r3.cmd(remove_cmd)
        run.write_text('nfdc/r3_probe_route_remove.txt', remove_cmd + '\n' + remove_out)

        if fallback_during_f:
            run.event('phase_f_fallback_forbidden')
            return 1

        still_standby = bool(grep_node_log(
            r2, r'OptoFlood tfib-standby prefix=/LiveStream reason=fib-agrees').strip())
        run.event('standby_before_c', present=still_standby)
        run.save_nfdc(r2, 'pre_c')
        nlsr_r2 = nlsrs['r2']
        if nlsr_r2 is None:
            run.event('nlsr_r2_handle_missing')
            return 1
        nlsr_r2.stop()
        run.event('nlsr_r2_stopped')
        sleep(1)
        run.save_nfdc(r2, 'after_nlsr_stop')
        route_show = read_file(os.path.join(
            run.results_dir, 'nfdc', 'r2_after_nlsr_stop_route_show_livestream.txt'))
        nlsr_hops = parse_nlsr_nexthops(route_show)
        run.event('nlsr_livestream_hops', hops=nlsr_hops)
        offset_after_c = log_bytes(r2)
        run.event('phase_c_log_offset', offset=offset_after_c)
        for hop in nlsr_hops:
            cmd = f'nfdc route remove prefix /LiveStream nexthop {hop} origin nlsr'
            out = r2.cmd(cmd)
            run.write_text(f'nfdc/r2_route_remove_{hop}.txt', cmd + '\n' + out)
            run.event('route_remove', hop=hop, out=out.strip())
        # Expire ndn-cxx Dispatcher status-dataset IMS (FreshnessPeriod/insert 1s).
        # Not a routing-convergence wait.
        sleep(1.2)
        run.save_nfdc(r2, 'after_route_remove')
        face_after = read_file(os.path.join(run.results_dir, 'nfdc', 'r2_after_route_remove_face.txt'))
        tfib_face_alive = any(f['id'] == tfib_face for f in parse_face_list(face_after))
        run.event('tfib_face_alive_after_remove', alive=tfib_face_alive, face=tfib_face)
        if not tfib_face_alive:
            run.event('tfib_face_destroyed')
            return 1

        delivered_before = count_delivered(read_file(os.path.join(run.results_dir, 'consumer.log')))
        fb_text, _ = poll_grep_since(
            r2, r'OptoFlood tfib-fallback prefix=/LiveStream reason=', offset_after_c, 20.0)
        if fb_text and fb_text.strip():
            run.event('tfib_fallback', line=fb_text.strip().splitlines()[-1])
        fwd_text, _ = poll_grep_since(
            r2, r'OptoFlood tfib-forward interest=/LiveStream/v0', offset_after_c, 10.0)
        if fwd_text and fwd_text.strip():
            run.event('tfib_forward_after_c', line=fwd_text.strip().splitlines()[-1])
        out_text, _ = poll_grep_since(
            r2, rf'onOutgoingInterest out={tfib_face} interest=/LiveStream/v0',
            offset_after_c, 10.0)
        if out_text and out_text.strip():
            run.event('outgoing_after_c', line=out_text.strip().splitlines()[-1])
        sleep(3)
        delivered_after = count_delivered(read_file(os.path.join(run.results_dir, 'consumer.log')))
        run.event('consumer_delivered', before=delivered_before, after=delivered_after)
        return 0
    finally:
        teardown(run, ndn, nodes)


def cell_r(run: CellRun) -> int:
    ndn, _nlsrs, nodes = start_common(run)
    r3 = nodes['r3']
    r4 = nodes['r4']
    r5 = nodes['r5']
    try:
        run.save_nfdc(r3, 'pre_mobility')
        face_r3 = read_file(os.path.join(run.results_dir, 'nfdc', 'r3_pre_mobility_face.txt'))
        r3_to_r4 = face_id_toward(r3, r4, face_r3)
        r3_to_r5 = face_id_toward(r3, r5, face_r3)
        run.event('r3_face_map', r3_to_r4=r3_to_r4, r3_to_r5=r3_to_r5)
        if not r3_to_r4 or not r3_to_r5:
            run.event('r3_face_map_incomplete')
            return 1

        handoff(ndn, run, 'r2', 'r3')
        sleep(RAPID_GAP_S)
        handoff(ndn, run, 'r3', 'r4')
        t_r3r4 = wall()
        s1_text, s1_wall = poll_grep(
            r3, rf'OptoFlood TFIB update prefix=/LiveStream face={r3_to_r4} ', RAPID_GAP_S)
        s1 = first_tfib_update_for_face(
            s1_text or grep_node_log(r3, 'TFIB update prefix=/LiveStream'), r3_to_r4)
        if s1:
            run.event('s1_tfib_update', **s1, seen_at=s1.get('log_ts', s1_wall))
        else:
            run.event('s1_tfib_update_missing', face=r3_to_r4)
        remain = RAPID_GAP_S - (wall() - t_r3r4)
        if remain > 0:
            sleep(remain)

        handoff(ndn, run, 'r4', 'r5')
        s2_text, s2_wall = poll_grep(
            r3, rf'OptoFlood TFIB update prefix=/LiveStream face={r3_to_r5} ', 30.0)
        s2 = highest_tfib_update_for_face(s2_text or '', r3_to_r5)
        if not s2:
            s2 = highest_tfib_update_for_face(
                grep_node_log(r3, 'TFIB update prefix=/LiveStream'), r3_to_r5)
            s2_wall = wall()
        if s2:
            insert_final = s2.get('log_ts', s2_wall)
            run.event('s2_tfib_update', **s2, seen_at=insert_final)
        else:
            run.event('s2_tfib_update_missing', face=r3_to_r5)
            return 1

        offset_s2 = log_bytes(r3)
        fwd, _ = poll_grep_since(
            r3,
            rf'onOutgoingInterest out={r3_to_r5} interest=/LiveStream/',
            offset_s2, 20.0)
        if fwd and fwd.strip():
            run.event('s2_outgoing', line=fwd.strip().splitlines()[-1], face=r3_to_r5)
        tfib_fwd, _ = poll_grep_since(
            r3, r'OptoFlood tfib-forward interest=/LiveStream/', offset_s2, 10.0)
        if tfib_fwd and tfib_fwd.strip():
            run.event('s2_tfib_forward', line=tfib_fwd.strip().splitlines()[-1])

        run.save_nfdc(r3, 'after_s2')
        retire_deadline = insert_final + HARD_DEADLINE_WAIT_S
        run.event('hard_deadline_wait', insert_final=insert_final,
                  deadline=retire_deadline)
        standby_seen = False
        retire_seen = False
        fallback_seen = False
        offset_after_s2_standby = None
        while wall() < retire_deadline:
            if not standby_seen:
                standby_log = grep_node_log(
                    r3, r'OptoFlood tfib-standby prefix=/LiveStream reason=fib-agrees')
                if standby_log.strip():
                    standby_seen = True
                    offset_after_s2_standby = log_bytes(r3)
                    line = standby_log.strip().splitlines()[-1]
                    run.event('tfib_standby', line=line,
                              seen_at=parse_nfd_ts(line) or wall())
            if not retire_seen:
                retire = grep_node_log(
                    r3, r'OptoFlood tfib-retire prefix=/LiveStream reason=expired')
                if retire.strip():
                    retire_seen = True
                    line = retire.strip().splitlines()[-1]
                    run.event('tfib_retire', line=line,
                              seen_at=parse_nfd_ts(line) or wall())
            if standby_seen and not fallback_seen:
                fb_src = (
                    grep_since(
                        r3, r'OptoFlood tfib-fallback prefix=/LiveStream',
                        offset_after_s2_standby)
                    if offset_after_s2_standby is not None else '')
                if fb_src.strip():
                    fallback_seen = True
                    line = fb_src.strip().splitlines()[-1]
                    run.event('s2_fallback_after_standby', line=line,
                              seen_at=parse_nfd_ts(line) or wall())
                    offset_fb = log_bytes(r3)
                    fwd_fb, _ = poll_grep_since(
                        r3, r'OptoFlood tfib-forward interest=/LiveStream/',
                        offset_fb, 10.0)
                    if fwd_fb and fwd_fb.strip():
                        run.event('s2_tfib_forward_after_fallback',
                                  line=fwd_fb.strip().splitlines()[-1])
                    out_fb, _ = poll_grep_since(
                        r3,
                        rf'onOutgoingInterest out={r3_to_r5} interest=/LiveStream/',
                        offset_fb, 10.0)
                    if out_fb and out_fb.strip():
                        run.event('s2_outgoing_after_fallback',
                                  line=out_fb.strip().splitlines()[-1],
                                  face=r3_to_r5)
            sleep(0.25)
        if not retire_seen:
            retire = grep_node_log(r3, r'OptoFlood tfib-retire prefix=/LiveStream reason=expired')
            if retire.strip():
                line = retire.strip().splitlines()[-1]
                run.event('tfib_retire', line=line,
                          seen_at=parse_nfd_ts(line) or wall())
            else:
                run.event('tfib_retire_not_seen')
        if not standby_seen:
            run.event('tfib_standby_not_reached', waited_s=HARD_DEADLINE_WAIT_S)
        return 0
    finally:
        teardown(run, ndn, nodes)


def main() -> int:
    setLogLevel('info')
    experiment_dir = os.getenv('EXPERIMENT_DIR')
    if not experiment_dir:
        print('Error: EXPERIMENT_DIR is not set')
        return 1
    cell = (os.getenv('R2_CELL') or '').strip().upper()
    if cell not in ('A', 'CF', 'R'):
        print('Error: R2_CELL must be A, CF, or R')
        return 2
    results_dir = os.path.join(experiment_dir, 'results', cell)
    if os.path.isdir(results_dir):
        shutil.rmtree(results_dir)
    run = CellRun(cell, experiment_dir, results_dir)
    try:
        if cell == 'A':
            return cell_a(run)
        if cell == 'CF':
            return cell_cf(run)
        return cell_r(run)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        run.event('system_exit', code=code, message=str(exc))
        return code


if __name__ == '__main__':
    raise SystemExit(main())
