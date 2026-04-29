"""Run RFC calls under a wall-clock timeout.

Background: pyrfc / the SAP NW RFC SDK does not expose a per-call cancellation
API. A hung `Connection.call(...)` blocks the calling thread forever — there
is no portable way to interrupt it. This module gives every tool a uniform
upper bound on call duration by running the work in a single-shot worker
thread and abandoning it if it doesn't finish in time.

Tradeoff: an abandoned worker keeps the underlying SAP connection until the
gateway / work process tears it down on its own (typically several minutes
for stuck dialog work processes). That's accepted — one orphan per timeout
event is far cheaper than a tool that never returns.
"""
from __future__ import annotations

import concurrent.futures
from typing import Any, Callable

import keyring

from connection import SERVICE_NAME

DEFAULT_RFC_TIMEOUT = 60
PING_TIMEOUT = 10


def get_rfc_timeout(default: int = DEFAULT_RFC_TIMEOUT) -> int:
    """Read rfc_timeout from the keyring; fall back to `default` on missing/invalid."""
    raw = keyring.get_password(SERVICE_NAME, "rfc_timeout")
    if not raw:
        return default
    try:
        n = int(raw)
        return n if n > 0 else default
    except ValueError:
        return default


class RFCTimeout(Exception):
    """Raised when an RFC call does not complete within the configured timeout."""


def with_timeout(fn: Callable[..., Any], *args, seconds: int | None = None, **kwargs) -> Any:
    """Run `fn(*args, **kwargs)` with a wall-clock cap.

    `seconds` overrides the keyring/default (use PING_TIMEOUT for cheap
    health checks, leave None for the default).

    Raises:
        RFCTimeout: if the call did not return within the timeout.

    The worker is leaked on timeout — see module docstring.
    """
    timeout = seconds if seconds is not None else get_rfc_timeout()
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = ex.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise RFCTimeout(
            f"RFC call did not complete within {timeout}s "
            f"(configurable via keyring key 'rfc_timeout')"
        )
    finally:
        # Don't wait on the leaked worker. shutdown(wait=False) lets the
        # interpreter reap the thread when the SDK eventually unblocks.
        ex.shutdown(wait=False)
