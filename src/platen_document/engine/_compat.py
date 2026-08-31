"""Small neutral runtime helpers extracted from the PDFNest worker.

These helpers intentionally contain no PDFNest application concepts. They
provide the subprocess and local Tesseract-capacity boundaries required by the
copied engine modules.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Generator

logger = logging.getLogger(__name__)


def kill_process_group(pgid: int, term_grace_seconds: float = 1.0) -> None:
    """Terminate a subprocess group so timed-out children do not survive."""
    if pgid <= 1:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    deadline = time.time() + term_grace_seconds
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
            time.sleep(0.05)
        except (ProcessLookupError, OSError):
            return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        return


def run_hardened_subprocess(
    cmd: list[str],
    *,
    timeout: float = 300.0,
    cancellation_check: Callable[[], None] | None = None,
    term_grace_seconds: float = 1.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command in its own process group with bounded cleanup."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    deadline = time.time() + timeout
    while True:
        retcode = proc.poll()
        if retcode is not None:
            stdout, stderr = proc.communicate()
            return subprocess.CompletedProcess(cmd, retcode, stdout, stderr)
        if cancellation_check is not None:
            try:
                cancellation_check()
            except Exception:
                kill_process_group(pgid, term_grace_seconds)
                proc.communicate()
                raise
        if time.time() > deadline:
            kill_process_group(pgid, term_grace_seconds)
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=stdout, stderr=stderr)
        time.sleep(0.1)


GLOBAL_TESSERACT_CAPACITY = max(1, int(os.environ.get("GLOBAL_TESSERACT_CAPACITY", "2")))
_tesseract_semaphore = threading.BoundedSemaphore(GLOBAL_TESSERACT_CAPACITY)


class TesseractCapacityTimeoutError(Exception):
    """Tesseract capacity could not be acquired within the configured bound."""


@contextmanager
def acquire_tesseract_capacity(
    cancellation_check: Callable[[], None] | None = None,
    timeout: float | None = 60.0,
) -> Generator[None, None, None]:
    """Bound concurrent Tesseract processes and preserve cooperative cancel."""
    started = time.monotonic()
    acquired = False
    try:
        while not acquired:
            if cancellation_check is not None:
                cancellation_check()
            acquired = _tesseract_semaphore.acquire(timeout=0.5)
            if acquired:
                break
            if timeout is not None and time.monotonic() - started >= timeout:
                raise TesseractCapacityTimeoutError(
                    f"Tesseract capacity exhausted ({GLOBAL_TESSERACT_CAPACITY} max processes)"
                )
        yield
    finally:
        if acquired:
            _tesseract_semaphore.release()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
