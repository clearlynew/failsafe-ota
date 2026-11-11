"""Test-only fault injection. Inert unless the env vars below are set.

FAILSAFE_FAULT=<point>                 os._exit(137) when that point is reached
FAILSAFE_NET_BLACKHOLE=<point>:<secs>  drop all network I/O for <secs> once <point> is hit
"""
import contextlib
import os
import time

_blackhole_until = 0.0
_fired = False


def maybe_crash(point: str) -> None:
    """Simulated power cut: skips finally blocks and Python-level buffers."""
    if os.environ.get("FAILSAFE_FAULT") == point:
        os._exit(137)


def _start_blackhole(seconds: float) -> None:
    global _blackhole_until
    _blackhole_until = max(_blackhole_until, time.monotonic() + seconds)


def net_checkpoint(point: str) -> None:
    """Start the env-configured blackhole the first time `point` is reached."""
    global _fired
    spec = os.environ.get("FAILSAFE_NET_BLACKHOLE")
    if not spec or _fired:
        return
    name, secs = spec.split(":")
    if name == point:
        _fired = True
        _start_blackhole(float(secs))


@contextlib.contextmanager
def net_fault(blackhole_s: float):
    """In-process convenience: blackhole the network inside the with-block."""
    global _blackhole_until
    _start_blackhole(blackhole_s)
    try:
        yield
    finally:
        _blackhole_until = 0.0


def net_blackholed() -> bool:
    return time.monotonic() < _blackhole_until
