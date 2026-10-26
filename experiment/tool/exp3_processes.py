"""Exp3 application and daemon process records. No Mini-NDN import."""

from __future__ import annotations

import re
from typing import Literal, Sequence, Tuple

PROCESS_KINDS = (
    "producer-app",
    "consumer-app",
    "producer-daemon",
    "consumer-daemon",
)
HEALTH_HEADER = "host\tkind\tpid\tevent\trel_s\tdetail\n"
HEALTH_EVENTS = ("premature-exit", "intentional-shutdown", "shutdown-refused")


class ProcessError(ValueError):
    """Raised when a managed-process command cannot be identified safely."""


class Capture:
    def __init__(self, host: str, pid: int, pcap: str, log: str) -> None:
        if pid <= 1:
            raise ProcessError(f"refusing to manage tcpdump pid {pid}")
        self.host = host
        self.pid = pid
        self.pcap = pcap
        self.log = log
        self.dead = False


class ManagedProcess:
    def __init__(self, host: str, kind: str, pid: int, executable: str, role: str) -> None:
        if kind not in PROCESS_KINDS:
            raise ProcessError(f"unknown process kind {kind}")
        if pid <= 1:
            raise ProcessError(f"refusing to manage pid {pid}")
        self.host = host
        self.kind = kind
        self.pid = pid
        self.executable = executable
        self.role = role
        self.premature = False


def background_launch(env: str, executable: str, argument: str, log_path: str) -> str:
    """One shell command that backgrounds a process and prints only its pid."""
    suffix = f" {argument}" if argument else ""
    prefix = f"{env} " if env else ""
    return f"{prefix}{executable}{suffix} >> {log_path} 2>&1 & echo $!"


def parse_background_pid(output: str) -> int:
    found = []
    for line in output.splitlines():
        token = line.strip()
        if token.isdigit():
            found.append(int(token))
    if len(found) != 1 or found[0] <= 1:
        raise ProcessError(f"background pid not identified: {output!r}")
    return found[0]


def trailing_status(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def command_owns_pid(cmdline: str, executable: str, role: str) -> bool:
    """True only when this pid's command is the executable the driver started.

    A recycled pid, NFD, or NLSR does not match and must not be signalled.
    """
    tokens = cmdline.split()
    base = executable.rsplit("/", 1)[-1]
    names = {token.rsplit("/", 1)[-1] for token in tokens}
    if executable not in tokens and base not in names:
        return False
    if role and role not in tokens:
        return False
    return True


def command_owns_capture(cmdline: str, pcap_path: str) -> bool:
    """True only for the tcpdump writing this capture file."""
    return command_owns_pid(cmdline, "tcpdump", "") and pcap_path in cmdline.split()


# echo $! returns at fork. tcpdump's cmdline appears only after exec. Each
# observation is a Mininet shell round trip, so the bound covers several of
# those trips. A matching observation returns immediately; this is not a sleep.
CAPTURE_STARTUP_TIMEOUT_S = 2.0
CAPTURE_STARTUP_POLL_S = 0.05
_RUNNING_STATES = set("RSDTtWIP")
_TRANSIENT_SHELLS = {"sh", "bash", "dash", "busybox"}


def process_state(stat_text: str) -> str:
    """Return the state character from /proc/pid/stat, or empty when absent."""
    for line in stat_text.splitlines():
        end = line.rfind(")")
        if end < 0 or end + 2 >= len(line):
            continue
        rest = line[end + 2:].strip()
        if rest:
            return rest.split(None, 1)[0]
    return ""


def pid_state_is_running(state: str) -> bool:
    """False for a missing process, a zombie, or a dead task."""
    return state in _RUNNING_STATES


def split_capture_observation(output: str) -> Tuple[str, str]:
    """Split one combined /proc snapshot into state and command line."""
    state_text, marker, command_text = output.partition("__CMDLINE__")
    if not marker:
        return "", ""
    return process_state(state_text.replace("__STATE__", "")), " ".join(command_text.split())


def _transient_shell(cmdline: str) -> bool:
    tokens = cmdline.split()
    if not tokens:
        return True
    name = tokens[0].rsplit("/", 1)[-1].lstrip("-")
    return name in _TRANSIENT_SHELLS


def capture_startup_status(state: str, cmdline: str, pcap_path: str) -> str:
    """Classify one startup observation: ready, wait, exited, or mismatch."""
    if not pid_state_is_running(state):
        return "exited"
    if command_owns_capture(cmdline, pcap_path):
        return "ready"
    if _transient_shell(cmdline):
        return "wait"
    return "mismatch"


def resolve_capture_startup(
    observations: Sequence[Tuple[str, str]],
    pcap_path: str,
    timeout_s: float = CAPTURE_STARTUP_TIMEOUT_S,
    poll_s: float = CAPTURE_STARTUP_POLL_S,
) -> str:
    """Resolve ordered (state, cmdline) observations. The first is at fork time.

    A trace that is still a transient shell before the deadline stays ``wait``.
    The driver polls again. ``timeout`` means the deadline was reached first.
    """
    elapsed = 0.0
    for state, cmdline in observations:
        status = capture_startup_status(state, cmdline, pcap_path)
        if status != "wait":
            return status
        if elapsed >= timeout_s:
            return "timeout"
        elapsed += poll_s
    if elapsed >= timeout_s:
        return "timeout"
    return "wait"


def capture_stop_allowed(cmdline: str, pcap_path: str) -> bool:
    """Signal only the tcpdump that owns this capture. A shell or recycled pid does not."""
    return command_owns_capture(cmdline, pcap_path)


def capture_failure_message(
    host: str,
    pid: int,
    status: str,
    state: str,
    cmdline: str,
    log_text: str,
) -> str:
    """PID, identity, and tcpdump stderr for a startup failure. The run does not continue."""
    log = log_text.strip() or "<empty>"
    if len(log) > 1000:
        log = log[-1000:]
    return (
        f"tcpdump startup {status} on {host} pid {pid}: "
        f"state={state or 'absent'} cmdline={cmdline or '<empty>'}\n{log}"
    )


def health_row(host: str, kind: str, pid: int, event: str, rel_s: float, detail: str) -> str:
    if kind not in PROCESS_KINDS:
        raise ProcessError(f"unknown process kind {kind}")
    if event not in HEALTH_EVENTS:
        raise ProcessError(f"unknown process event {event}")
    if pid <= 1:
        raise ProcessError(f"refusing to record pid {pid}")
    return f"{host}\t{kind}\t{pid}\t{event}\t{rel_s:.6f}\t{detail}\n"


def expected_processes(producers: Sequence[str], consumers: Sequence[str]) -> Tuple[Tuple[str, str], ...]:
    rows: list[Tuple[str, str]] = []
    for producer, consumer in zip(producers, consumers):
        rows.extend((
            (producer, "producer-app"),
            (consumer, "consumer-app"),
            (producer, "producer-daemon"),
            (consumer, "consumer-daemon"),
        ))
    return tuple(rows)


_PCAP_MAGICS: dict[bytes, Literal["little", "big"]] = {
    b"\xd4\xc3\xb2\xa1": "little",
    b"\xa1\xb2\xc3\xd4": "big",
    b"\x4d\x3c\xb2\xa1": "little",
    b"\xa1\xb2\x3c\x4d": "big",
}
_CAPTURED = re.compile(r"(\d+) packets captured")
_KERNEL_DROPS = re.compile(r"(\d+) packets dropped by kernel")
_INTERFACE_DROPS = re.compile(r"(\d+) packets dropped by interface")


def inspect_pcap(data: bytes) -> Tuple[str, int]:
    """Walk a classic pcap. Empty payload with a valid header is decodable."""
    if len(data) < 24:
        return "truncated-header", 0
    endian = _PCAP_MAGICS.get(data[:4])
    if endian is None:
        return "bad-magic", 0
    offset = 24
    count = 0
    while offset < len(data):
        if offset + 16 > len(data):
            return "truncated-record", count
        included = int.from_bytes(data[offset + 8:offset + 12], endian)
        if included > 262144:
            return "bad-record", count
        nxt = offset + 16 + included
        if nxt > len(data):
            return "truncated-record", count
        offset = nxt
        count += 1
    if count == 0:
        return "ok-empty", 0
    return "ok", count


def tcpdump_drop_detail(log_text: str) -> str:
    """Return kernel and interface drop counts, or 'unavailable' when tcpdump did not report them."""
    kernel = _KERNEL_DROPS.search(log_text)
    interface = _INTERFACE_DROPS.search(log_text)
    captured = _CAPTURED.search(log_text)
    if kernel is None and interface is None and captured is None:
        return "unavailable"
    kernel_n = kernel.group(1) if kernel else "absent"
    interface_n = interface.group(1) if interface else "absent"
    captured_n = captured.group(1) if captured else "absent"
    return f"captured={captured_n} kernel_dropped={kernel_n} interface_dropped={interface_n}"
