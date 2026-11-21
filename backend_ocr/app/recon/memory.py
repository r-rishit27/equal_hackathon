"""Memory headroom on a small box (03_LLD_BACKEND.md §15).

The backend shares ~1 GB with the production API. Reading a scanned file is the
heaviest thing Recon does, so before each page image it checks what the kernel
says is available; short of RECON_MIN_FREE_MB it stops cleanly and the worker
puts the file back in the queue to try later — instead of pushing the box into
swapless thrash, which froze prod and dev on 2026-11-13.
"""
from __future__ import annotations

import gc

from . import config as C


class MemoryPressure(RuntimeError):
    """Not enough free memory to read safely right now; try again later."""


def available_mb() -> int | None:
    """MemAvailable from /proc/meminfo, or None where there is no such file (macOS dev machines)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def ensure_headroom(min_mb: int | None = None) -> None:
    need = C.MIN_FREE_MB if min_mb is None else min_mb
    have = available_mb()
    if have is None or have >= need:
        return
    gc.collect()                                  # our own garbage first
    have = available_mb()
    if have is not None and have < need:
        raise MemoryPressure(f"only {have} MB free (need {need} MB)")
