"""Kill Thunderbolt process trees safely on any platform using psutil.

Used by scripts/cli.mjs as the single-instance guard: before a new launcher
spawns its stack, every leftover Thunderbolt process from a previous run
(another launcher, orphan workers that survived their launcher, an orphaned
MoneyPrinterTurbo agent) is terminated so exactly one stack keeps running.

Usage:
  python kill_tree.py --cleanup <exclude_pid>
      Kill every Thunderbolt-related process outside the exclude pid's tree.
      The exclude pid, its ancestors and this helper's own tree are preserved.
  python kill_tree.py --pid <pid>
      Kill only the tree rooted at <pid> (children first, then the parent).

Both modes print a JSON summary on stdout:
  {"killed": [pid, ...], "survivors": [pid, ...], "excluded": [pid, ...]}
Exit code is 0 when every targeted process ended, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a hard app dependency
    print(json.dumps({"error": "psutil não está instalado"}))
    sys.exit(1)


# Command-line fragments that identify a Thunderbolt process. Matching is
# case-insensitive and applies to the full command line so it works for the
# npx wrappers on Windows ("npx.cmd --yes ... @danhachuel/thunderbolt") and
# for POSIX shells alike. The helper's own command line contains
# "kill_tree.py", which is NOT in the list, so the helper never targets itself
# through these markers.
THUNDERBOLT_MARKERS = (
    "@danhachuel/thunderbolt",
    "scripts/cli.mjs",
    "hermes_ui.pipeline_worker",
    "hermes_ui.automation_worker",
    "streamlit_bootstrap.py",
    "mpt_agent.py",
)


def is_thunderbolt_process(process: psutil.Process) -> bool:
    try:
        cmdline = " ".join(process.cmdline()).lower()
    except (psutil.Error, OSError):
        return False
    if not cmdline.strip():
        return False
    # This helper runs inside the package; never match the kill helper itself.
    if "kill_tree.py" in cmdline:
        return False
    return any(marker in cmdline for marker in THUNDERBOLT_MARKERS)


def ancestor_pids(process: psutil.Process) -> set[int]:
    pids: set[int] = set()
    current = process
    while True:
        try:
            pids.add(current.pid)
            current = current.parent()
            if current is None:
                break
        except (psutil.Error, OSError):
            break
    return pids


def protected_pids(exclude_pid: int | None) -> set[int]:
    """Pids that must never be killed: this helper, its ancestors, the
    exclude pid (the new launcher) and the exclude pid's ancestors (the
    terminal/npx chain that started it)."""
    protected = {os.getpid()}
    protected |= ancestor_pids(psutil.Process(os.getpid()))
    if exclude_pid:
        try:
            protected.add(int(exclude_pid))
            protected |= ancestor_pids(psutil.Process(int(exclude_pid)))
        except (psutil.Error, OSError, ValueError):
            pass
    return protected


def collect_tree(process: psutil.Process) -> list[psutil.Process]:
    try:
        children = process.children(recursive=True)
    except (psutil.Error, OSError):
        children = []
    return children + [process]


def terminate(targets: list[psutil.Process], wait_seconds: float = 3.0) -> tuple[list[int], list[int]]:
    """Terminate children first (so no orphans escape), then the roots."""
    processes: dict[int, psutil.Process] = {}
    target_pids: list[int] = []
    for process in targets:
        try:
            live = psutil.Process(process.pid)
        except (psutil.Error, OSError):
            continue
        processes[live.pid] = live
        target_pids.append(live.pid)
    # Children were collected before their parents: terminating in that order
    # means each parent is still around to be terminated afterwards.
    for process in processes.values():
        try:
            process.terminate()
        except (psutil.Error, OSError):
            pass
    alive = dict(processes)
    deadline = time.monotonic() + wait_seconds
    while alive and time.monotonic() < deadline:
        alive = {pid: process for pid, process in alive.items() if process.is_running()}
        if alive:
            time.sleep(0.1)
    for process in alive.values():
        try:
            process.kill()
        except (psutil.Error, OSError):
            pass
    time.sleep(0.3)
    survivors: list[int] = []
    for pid in alive:
        try:
            if psutil.Process(pid).is_running():
                survivors.append(pid)
        except (psutil.Error, OSError):
            pass  # the process ended between checks
    killed = [pid for pid in target_pids if pid not in survivors]
    return killed, survivors


def cleanup(exclude_pid: int | None) -> dict[str, list[int]]:
    protected = protected_pids(exclude_pid)
    roots: list[psutil.Process] = []
    targeted: set[int] = set()
    for process in psutil.process_iter(["pid"]):
        pid = process.pid
        if pid in protected or pid in targeted:
            continue
        if not is_thunderbolt_process(process):
            continue
        # Kill whole trees; mark every member so a child of two matched roots
        # is not targeted twice.
        for member in collect_tree(process):
            try:
                if member.pid in protected:
                    continue
                if member.pid not in targeted:
                    targeted.add(member.pid)
                    roots.append(member)
            except (psutil.Error, OSError):
                continue
    killed, survivors = terminate(roots)
    return {"killed": killed, "survivors": survivors, "excluded": sorted(protected)}


def kill_pid(pid: int) -> dict[str, list[int]]:
    try:
        process = psutil.Process(int(pid))
    except (psutil.Error, OSError, ValueError):
        return {"killed": [], "survivors": [], "excluded": []}
    killed, survivors = terminate(collect_tree(process))
    return {"killed": killed, "survivors": survivors, "excluded": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cleanup", nargs="?", const="-1", default=None, metavar="EXCLUDE_PID", help="kill every Thunderbolt process outside EXCLUDE_PID's tree")
    mode.add_argument("--pid", type=int, help="kill only the tree rooted at PID")
    args = parser.parse_args()

    if args.cleanup is not None:
        exclude = None
        try:
            exclude = int(args.cleanup)
        except ValueError:
            exclude = None
        summary = cleanup(exclude)
    else:
        summary = kill_pid(args.pid)

    print(json.dumps(summary))
    return 0 if not summary["survivors"] else 1


if __name__ == "__main__":
    sys.exit(main())
