"""Exp3 application and daemon process records. No Mini-NDN import."""

from __future__ import annotations

from typing import Sequence, Tuple

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
    if executable not in tokens and base not in tokens:
        return False
    if role and role not in tokens:
        return False
    return True


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
