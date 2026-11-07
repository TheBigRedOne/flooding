#!/usr/bin/env python3
"""One-command Exp3 P1 smoke that suspends producer1 and checks PROBING.

The Exp3 driver always writes to ``$EXPERIMENT_DIR/results``. This script
moves an existing ``results`` directory aside, runs one smoke, and archives
the new output under ``results_probing_<stamp>``. It does not modify the
driver. It never signals a process whose executable, advertised prefix, and
stdout log do not all identify this run's producer application.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


PROTECTED_NAMES = {
    "results_smoke_relative_pacing",
    "results_smoke_absolute_pacing",
}
PRODUCER_HOST = "producer1"
PRODUCER_PREFIX = "/LiveStream/v0"
STOP_S = 5.0
STREAMING_WAIT_S = 90.0
STALL_LOW_MS = 1500.0
STALL_HIGH_MS = 3500.0
PACE_LOW_MS = 18.0
PACE_HIGH_MS = 22.0
PACE_GAP_MS = 5.0
MIN_PACE_INTERVALS = 10

_LINE = re.compile(r"^\[(\d+)\]\s+(.*)$")
_STREAMING = re.compile(r"^MODE: STREAMING\b.*\bL=(\d+)\b")
_PROBING = re.compile(r"^MODE: PROBING\b")
_DISCOVER = re.compile(r"^DISCOVER: (\S+)\s*$")
_EDGE = re.compile(r"^DISCOVER: live edge = (\d+)\s*$")
_FRAME = re.compile(r"^FRAME: start frame=(\d+)\b")
_DATA = re.compile(r"^DATA: frame=(\d+)\b")
_DELIVERED = re.compile(r"^FRAME: delivered frame=(\d+)\b")


@dataclass
class Event:
    ns: int
    kind: str
    value: str


@dataclass
class Identity:
    pid: int
    exe: str
    cmdline: Tuple[str, ...]
    prefix: str
    stdout: str


def _events(text: str) -> List[Event]:
    found: List[Event] = []
    for raw in text.splitlines():
        match = _LINE.match(raw.strip())
        if not match:
            continue
        ns = int(match.group(1))
        body = match.group(2)
        streaming = _STREAMING.match(body)
        if streaming:
            found.append(Event(ns, "streaming", streaming.group(1)))
            continue
        if _PROBING.match(body):
            found.append(Event(ns, "probing", ""))
            continue
        edge = _EDGE.match(body)
        if edge:
            found.append(Event(ns, "edge", edge.group(1)))
            continue
        discover = _DISCOVER.match(body)
        if discover:
            found.append(Event(ns, "discover", discover.group(1)))
            continue
        frame = _FRAME.match(body)
        if frame:
            found.append(Event(ns, "frame", frame.group(1)))
            continue
        data = _DATA.match(body)
        if data:
            found.append(Event(ns, "data", data.group(1)))
            continue
        delivered = _DELIVERED.match(body)
        if delivered:
            found.append(Event(ns, "delivered", delivered.group(1)))
    return found


def _ms(later: int, earlier: int) -> float:
    return (later - earlier) / 1_000_000.0


def evaluate(text: str) -> Tuple[str, List[str]]:
    """Return PASS, FAIL, or UNKNOWN plus the reasons for a consumer log."""
    reasons: List[str] = []
    events = _events(text)
    streaming = [item for item in events if item.kind == "streaming"]
    probing = [item for item in events if item.kind == "probing"]
    if not streaming:
        return "FAIL", ["no MODE: STREAMING line"]
    if not probing:
        return "FAIL", ["no MODE: PROBING line"]
    first = streaming[0]
    probe = next((item for item in probing if item.ns > first.ns), None)
    if probe is None:
        return "FAIL", ["PROBING is not after the initial STREAMING"]
    second = next((item for item in streaming if item.ns > probe.ns), None)
    if second is None:
        return "FAIL", ["no STREAMING re-entry after PROBING"]
    lead = int(second.value)

    progress = [
        item for item in events
        if item.kind in {"data", "delivered"} and first.ns <= item.ns < probe.ns
    ]
    if not progress:
        reasons.append("no Content progress between initial STREAMING and PROBING")
    else:
        gap = _ms(probe.ns, progress[-1].ns)
        if not STALL_LOW_MS <= gap <= STALL_HIGH_MS:
            reasons.append(
                f"PROBING at {_ms(probe.ns, progress[-1].ns):.1f} ms after last Content progress; "
                f"expected {STALL_LOW_MS:.0f}-{STALL_HIGH_MS:.0f} ms"
            )

    discoveries = [
        item for item in events
        if probe.ns <= item.ns <= second.ns and item.kind == "discover"
    ]
    edges = [
        item for item in events
        if probe.ns <= item.ns <= second.ns and item.kind == "edge"
    ]
    edge_ns = edges[-1].ns if edges else second.ns
    during = [
        item for item in events
        if item.kind == "frame" and probe.ns < item.ns < edge_ns
    ]
    if during:
        reasons.append(f"{len(during)} FRAME start lines during PROBING")
    if not discoveries:
        reasons.append("no _meta DISCOVER attempt while PROBING")
    if not edges:
        reasons.append("no successful _meta live-edge reply before STREAMING re-entry")

    refill = [
        item for item in events
        if item.kind == "frame" and edges and edges[-1].ns <= item.ns <= second.ns
    ]
    if len(refill) > lead + 2:
        reasons.append(
            f"rediscovery requested {len(refill)} frames before STREAMING; lookahead L={lead}"
        )
    resumed = [
        item for item in events
        if item.kind in {"data", "delivered"} and item.ns > second.ns
    ]
    if not resumed:
        reasons.append("no Content delivery after STREAMING re-entry")

    early = [
        item for item in events
        if item.kind == "frame" and second.ns < item.ns <= second.ns + 100_000_000
    ]
    if len(early) > 3:
        reasons.append(
            f"{len(early)} FRAME starts in the 100 ms after STREAMING; "
            "this exceeds one resumed pace tick"
        )
    paced = [
        item for item in events
        if item.kind == "frame" and item.ns > second.ns + 100_000_000
    ]
    intervals: List[float] = []
    previous: Optional[Event] = None
    for item in paced:
        if previous is not None and int(item.value) == int(previous.value) + 1:
            gap = _ms(item.ns, previous.ns)
            if gap > PACE_GAP_MS:
                intervals.append(gap)
        previous = item
    if len(intervals) < MIN_PACE_INTERVALS:
        reasons.append(f"only {len(intervals)} resumed pacing intervals")
    else:
        midpoint = statistics.median(intervals)
        if not PACE_LOW_MS <= midpoint <= PACE_HIGH_MS:
            reasons.append(f"resumed pacing median {midpoint:.3f} ms")
    if reasons:
        return "FAIL", reasons
    return "PASS", [
        f"PROBING at {_ms(probe.ns, progress[-1].ns):.1f} ms after last Content progress",
        f"rediscovery lookahead frames={len(refill)} L={lead}",
        f"resumed pacing intervals={len(intervals)} median={statistics.median(intervals):.3f} ms",
    ]


def _self_check() -> int:
    def line(ns: int, body: str) -> str:
        return f"[{ns}] {body}"

    start = 1_000_000_000_000_000_000
    rows = [
        line(start, "MODE: STREAMING edge=10 requestedUpTo=17 L=7"),
        line(start + 1_000_000_000, "DATA: frame=12 seg=0 Size: 100 bytes"),
        line(start + 3_100_000_000, "MODE: PROBING"),
        line(start + 3_100_000_000, "DISCOVER: /LiveStream/v0/_meta"),
        line(start + 6_200_000_000, "DISCOVER: live edge = 40"),
    ]
    for frame in range(41, 48):
        rows.append(line(start + 6_200_000_000, f"FRAME: start frame={frame}"))
    rows.append(line(start + 6_201_000_000, "MODE: STREAMING edge=40 requestedUpTo=47 L=7"))
    for index in range(20):
        ns = start + 6_301_000_000 + index * 20_000_000
        rows.append(line(ns, f"FRAME: start frame={48 + index}"))
        rows.append(line(ns + 5_000_000, f"DATA: frame={48 + index} seg=0 Size: 100 bytes"))
    status, reasons = evaluate("\n".join(rows))
    if status != "PASS":
        print("SELF-CHECK FAIL")
        for reason in reasons:
            print(f"  {reason}")
        return 1
    bad, bad_reasons = evaluate(line(start, "MODE: STREAMING edge=10 requestedUpTo=17 L=7"))
    if bad != "FAIL" or not any("PROBING" in reason for reason in bad_reasons):
        print("SELF-CHECK FAIL: missing PROBING was not rejected")
        return 1
    print("SELF-CHECK PASS")
    return 0


def _protected(path: Path) -> None:
    if path.name in PROTECTED_NAMES:
        raise RuntimeError(f"refusing to touch protected results {path}")


def _archive_existing(experiment_dir: Path, stamp: str) -> Optional[Path]:
    results = experiment_dir / "results"
    _protected(results)
    if not results.exists():
        return None
    preserved = experiment_dir / f"results_preserved_{stamp}"
    _protected(preserved)
    results.rename(preserved)
    return preserved


def _restore(experiment_dir: Path, preserved: Optional[Path], stamp: str) -> Path:
    results = experiment_dir / "results"
    archived = experiment_dir / f"results_probing_{stamp}"
    _protected(results)
    _protected(archived)
    if results.exists():
        if archived.exists():
            raise RuntimeError(f"archive destination already exists: {archived}")
        results.rename(archived)
    if not archived.exists():
        archived.mkdir()
    if preserved is not None:
        if results.exists():
            raise RuntimeError(f"cannot restore {preserved}; {results} exists")
        preserved.rename(results)
    return archived


def _cmdline(pid: int) -> Tuple[str, ...]:
    raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    return tuple(part.decode("utf-8", "replace") for part in raw.split(b"\0") if part)


def _environ(pid: int) -> Dict[str, str]:
    raw = Path(f"/proc/{pid}/environ").read_bytes()
    values: Dict[str, str] = {}
    for part in raw.split(b"\0"):
        if not part or b"=" not in part:
            continue
        key, value = part.split(b"=", 1)
        values[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return values


def _state(pid: int) -> str:
    text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    end = text.rfind(")")
    if end < 0 or end + 2 >= len(text):
        return ""
    rest = text[end + 2:].strip()
    return rest.split(None, 1)[0] if rest else ""


def _identity(pid: int, producer_bin: Path, producer_log: Path) -> Optional[Identity]:
    if not Path(f"/proc/{pid}").exists():
        return None
    try:
        command = _cmdline(pid)
        exe = os.path.realpath(os.readlink(f"/proc/{pid}/exe"))
        stdout = os.path.realpath(os.readlink(f"/proc/{pid}/fd/1"))
        env = _environ(pid)
    except OSError:
        return None
    if not command or os.path.realpath(command[0]) != os.path.realpath(producer_bin):
        return None
    if exe != os.path.realpath(producer_bin):
        return None
    if len(command) != 1:
        return None
    if env.get("EXP_ADVERTISED_PREFIX") != PRODUCER_PREFIX:
        return None
    if stdout != os.path.realpath(producer_log):
        return None
    return Identity(pid, exe, command, env["EXP_ADVERTISED_PREFIX"], stdout)


def find_producer(producer_bin: Path, producer_log: Path) -> Identity:
    matches: List[Identity] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        found = _identity(int(entry), producer_bin, producer_log)
        if found is not None and _state(found.pid) in set("RSDTtWIP"):
            matches.append(found)
    if len(matches) != 1:
        details = ", ".join(str(item.pid) for item in matches) or "none"
        raise RuntimeError(f"expected one producer1 application, found {len(matches)} ({details})")
    return matches[0]


class ProducerHold:
    """SIGSTOP one verified producer and SIGCONT it on every exit path."""

    def __init__(self, producer_bin: Path, producer_log: Path) -> None:
        self.producer_bin = producer_bin
        self.producer_log = producer_log
        self.identity: Optional[Identity] = None
        self.stopped = False

    def pause(self) -> Identity:
        identity = find_producer(self.producer_bin, self.producer_log)
        if _state(identity.pid) not in set("RSDtWI"):
            raise RuntimeError(f"producer pid {identity.pid} is not running (state {_state(identity.pid)})")
        os.kill(identity.pid, signal.SIGSTOP)
        self.identity = identity
        self.stopped = True
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and _state(identity.pid) != "T":
            time.sleep(0.05)
        if _state(identity.pid) != "T":
            self.resume()
            raise RuntimeError(f"producer pid {identity.pid} did not enter stopped state")
        return identity

    def resume(self) -> str:
        identity = self.identity
        self.stopped = False
        if identity is None:
            return "no producer was suspended"
        current = _identity(identity.pid, self.producer_bin, self.producer_log)
        if current is None:
            return f"pid {identity.pid} exited or no longer matches; no signal sent"
        if _state(identity.pid) == "T":
            os.kill(identity.pid, signal.SIGCONT)
            return f"SIGCONT pid {identity.pid}"
        return f"pid {identity.pid} state is {_state(identity.pid)}; no SIGCONT required"


def _install_resume(hold: ProducerHold) -> None:
    def _handle(signum: int, _frame: object) -> None:
        message = hold.resume()
        print(f"signal {signum}: {message}", file=sys.stderr)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def _wait_for_streaming(log_path: Path, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if "MODE: STREAMING " in text:
                return True
        time.sleep(0.2)
    return False


def _write_report(path: Path, status: str, driver_code: Optional[int], lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [f"status={status}", f"driver_exit={'' if driver_code is None else driver_code}"]
    body.extend(lines)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def run(experiment_dir: Path) -> int:
    if os.name != "posix":
        print("Error: this test must run inside the Linux test VM")
        return 2
    if os.geteuid() != 0:
        print("Error: run with sudo so the Producer process can be signalled")
        return 2
    experiment_dir = experiment_dir.resolve()
    driver = experiment_dir.parents[1] / "tool" / "exp3_driver.py"
    producer_bin = experiment_dir / "producer"
    for required in (driver, producer_bin, experiment_dir / "consumer", experiment_dir / "optoflood-daemon"):
        if not required.exists():
            print(f"Error: missing {required}")
            return 2
    stamp = time.strftime("%Y%m%dT%H%M%S")
    preserved = _archive_existing(experiment_dir, stamp)
    archived: Optional[Path] = None
    driver_log = experiment_dir / f".probing_driver_{stamp}.log"
    env = os.environ.copy()
    env.update({
        "EXPERIMENT_DIR": str(experiment_dir),
        "EXP3_POPULATION": "p1",
        "EXP3_SCHEDULE": "smoke",
        "EXP_REQUEST_INTERVAL_MS": "20",
        "EXP_TARGET_PARKED": "4",
        "EXP_STALL_MS": "2000",
        "EXP_PROBE_INTERVAL_MS": "1000",
    })
    consumer_log = experiment_dir / "results" / "consumer1.log"
    producer_log = experiment_dir / "results" / "producer1.log"
    hold = ProducerHold(producer_bin, producer_log)
    _install_resume(hold)
    driver_code: Optional[int] = None
    notes: List[str] = []
    try:
        with driver_log.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                [sys.executable, str(driver)],
                cwd=str(experiment_dir),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            try:
                if not _wait_for_streaming(consumer_log, time.monotonic() + STREAMING_WAIT_S):
                    notes.append("STREAMING was not observed; producer was not signalled")
                else:
                    identity = hold.pause()
                    notes.append(
                        f"SIGSTOP pid={identity.pid} exe={identity.exe} stdout={identity.stdout} "
                        f"prefix={identity.prefix}"
                    )
                    time.sleep(STOP_S)
                    notes.append(hold.resume())
            finally:
                if hold.stopped:
                    notes.append(hold.resume())
                driver_code = process.wait()
    finally:
        if hold.stopped:
            notes.append(hold.resume())
        archived = _restore(experiment_dir, preserved, stamp)
    if driver_log.exists():
        driver_log.replace(archived / "driver.log")
    consumer_text = ""
    archived_log = archived / "consumer1.log"
    if archived_log.exists():
        consumer_text = archived_log.read_text(encoding="utf-8", errors="replace")
    if driver_code != 0:
        status = "UNKNOWN"
        reasons = [f"experiment driver exited {driver_code}"] + notes
    elif not consumer_text:
        status = "FAIL"
        reasons = ["consumer1.log is missing"] + notes
    else:
        status, reasons = evaluate(consumer_text)
        reasons = list(reasons) + notes
    report = archived / "probing-report.txt"
    _write_report(report, status, driver_code, reasons)
    print(f"status={status}")
    print(f"report={report}")
    for reason in reasons:
        print(reason)
    if driver_code not in (0, None):
        return driver_code
    return 0 if status == "PASS" else 1


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the Consumer PROBING lifecycle smoke")
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        default=Path("/home/vagrant/flooding/experiment/extended/exp3"),
    )
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    if args.self_check:
        return _self_check()
    try:
        return run(args.experiment_dir)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
