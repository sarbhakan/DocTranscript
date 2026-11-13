"""Sample Windows private commit and CPU time for a process tree."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _MemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _WindowsProcesses:
    def __init__(self) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)

        def bind(dll: object, name: str, result: object, *args: object):
            func = getattr(dll, name)
            func.argtypes = args
            func.restype = result
            return func

        self._snapshot = bind(kernel, "CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
        entry_ptr = ctypes.POINTER(_ProcessEntry)
        self._first = bind(kernel, "Process32FirstW", wintypes.BOOL, wintypes.HANDLE, entry_ptr)
        self._next = bind(kernel, "Process32NextW", wintypes.BOOL, wintypes.HANDLE, entry_ptr)
        self._open = bind(kernel, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self._close = bind(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
        self._memory = bind(
            psapi, "GetProcessMemoryInfo", wintypes.BOOL, wintypes.HANDLE,
            ctypes.POINTER(_MemoryCounters), wintypes.DWORD,
        )
        filetime_ptr = ctypes.POINTER(wintypes.FILETIME)
        self._times = bind(kernel, "GetProcessTimes", wintypes.BOOL, wintypes.HANDLE, *([filetime_ptr] * 4))

    def parent_ids(self) -> dict[int, int]:
        # TH32CS_SNAPPROCESS. The name field in each entry is deliberately ignored.
        handle = self._snapshot(0x00000002, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        parents: dict[int, int] = {}
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            if not self._first(handle, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error())
            while True:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                if not self._next(handle, ctypes.byref(entry)):
                    error = ctypes.get_last_error()
                    if error != 18:  # ERROR_NO_MORE_FILES
                        raise ctypes.WinError(error)
                    return parents
        finally:
            self._close(handle)

    def stats(self, pid: int) -> tuple[int | None, int | None, int | None]:
        # PROCESS_QUERY_LIMITED_INFORMATION; no elevation or memory-content read.
        process = self._open(0x1000, False, pid)
        if not process:
            return None, None, None
        try:
            counters = _MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            private = None
            if self._memory(process, ctypes.byref(counters), counters.cb):
                private = int(counters.PrivateUsage)
            creation, end, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if self._times(process, ctypes.byref(creation), ctypes.byref(end), ctypes.byref(kernel), ctypes.byref(user)):
                return private, _filetime_value(creation), _filetime_value(kernel) + _filetime_value(user)
            return private, None, None
        finally:
            self._close(process)


def _filetime_value(value: wintypes.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _tree(root: int, parents: dict[int, int]) -> set[int]:
    children: dict[int, list[int]] = {}
    for pid, parent in parents.items():
        children.setdefault(parent, []).append(pid)
    visited = {root}
    pending = [root]
    while pending:
        parent = pending.pop()
        for pid in children.get(parent, ()):
            if pid not in visited:
                visited.add(pid)
                pending.append(pid)
    return visited


def _sample(command: list[str], interval_ms: int) -> dict:
    windows = _WindowsProcesses()
    started = time.perf_counter()
    with subprocess.Popen(command, shell=False) as proc:
        samples: list[dict] = []
        cpu_ticks: dict[tuple[int, int], int] = {}
        snapshot_errors = 0
        while proc.poll() is None:
            elapsed = time.perf_counter() - started
            try:
                tree = _tree(proc.pid, windows.parent_ids())
            except OSError:
                snapshot_errors += 1
            else:
                readable = []
                for pid in tree:
                    private, creation, ticks = windows.stats(pid)
                    if private is not None:
                        readable.append(private)
                    if creation is not None and ticks is not None:
                        cpu_ticks[(pid, creation)] = ticks
                samples.append({
                    "elapsed_ms": round(elapsed * 1000, 3),
                    "processes_seen": len(tree),
                    "processes_read": len(readable),
                    "private_bytes_sum": sum(readable) if readable else None,
                })
            try:
                proc.wait(timeout=interval_ms / 1000)
            except subprocess.TimeoutExpired:
                pass

        duration = time.perf_counter() - started
        totals = [sample["private_bytes_sum"] for sample in samples if sample["private_bytes_sum"] is not None]
        observed_cpu_s = sum(cpu_ticks.values()) / 10_000_000 if cpu_ticks else None
        return {
            "schema_version": 1,
            "interval_ms_requested": interval_ms,
            "duration_ms": round(duration * 1000, 3),
            "peak_sampled_private_bytes": max(totals, default=None),
            "observed_cpu_seconds": observed_cpu_s,
            "observed_mean_cpu_core_equivalents": (
                observed_cpu_s / duration if observed_cpu_s is not None and duration else None
            ),
            "snapshot_errors": snapshot_errors,
            "partial_samples": sum(sample["processes_read"] < sample["processes_seen"] for sample in samples),
            "exit_code": proc.returncode,
            "samples": samples,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new JSON file")
    parser.add_argument("--interval-ms", type=int, default=200)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command or args.command[0] != "--" or len(args.command) < 2:
        parser.error("specify a command after --")
    if not 20 <= args.interval_ms <= 5000:
        parser.error("--interval-ms must be between 20 and 5000")
    if os.name != "nt":
        parser.error("the process sampler requires Windows")

    try:
        with args.output.open("x", encoding="utf-8") as stream:
            result = _sample(args.command[1:], args.interval_ms)
            json.dump(result, stream, indent=2)
            stream.write("\n")
    except OSError as exc:
        parser.exit(2, f"Sampling failed: {exc}\n")
    if result["exit_code"]:
        return result["exit_code"]
    return 0 if result["peak_sampled_private_bytes"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
