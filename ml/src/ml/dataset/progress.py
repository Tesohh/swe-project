"""Small helpers shared by the stage scripts."""

import time


def format_duration(seconds: float) -> str:
    """ETA string like 12:34 or 1:02:03."""
    minutes, secs = divmod(int(seconds + 0.5), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def eta_string(start: float, done: int, total: int) -> str:
    """ETA for total work items from the rate since start."""
    if done == 0:
        return "?"
    return format_duration((time.monotonic() - start) / done * (total - done))
