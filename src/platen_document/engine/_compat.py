"""Small neutral runtime helpers extracted from the PDFNest worker.

These helpers intentionally contain no PDFNest application concepts. They
provide the subprocess and local Tesseract-capacity boundaries required by the
copied engine modules.
"""

from __future__ import annotations

import logging
import locale
import math
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Generator

logger = logging.getLogger(__name__)
_PIPE_READ_BYTES = 64 * 1024


class SubprocessOutputLimitError(RuntimeError):
    """The command exceeded its combined stdout/stderr capture budget."""


def kill_process_group(pgid: int, term_grace_seconds: float = 1.0) -> None:
    """Terminate a subprocess group so timed-out children do not survive."""
    if pgid <= 1:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    deadline = time.monotonic() + term_grace_seconds
    while time.monotonic() < deadline:
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
    max_output_bytes: int = 16 * 1024 * 1024,
) -> subprocess.CompletedProcess[str]:
    """Run in an owned POSIX process group with bounded output and cleanup.

    ``max_output_bytes`` bounds raw stdout and stderr combined, not each
    stream independently. Exceeding it fails without returning truncated TSV.
    Successful output retains ``text=True`` decoding and newline semantics;
    timeout diagnostics use replacement decoding for incomplete final bytes.
    """
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be a positive integer")
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout must be finite and nonnegative")
    if not math.isfinite(term_grace_seconds) or term_grace_seconds < 0:
        raise ValueError("term_grace_seconds must be finite and nonnegative")
    encoding = "utf-8" if sys.flags.utf8_mode else locale.getencoding()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    captured_bytes = 0

    def text(name: str, *, errors: str = "strict") -> str:
        return output[name].decode(encoding, errors=errors).replace("\r\n", "\n").replace("\r", "\n")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    # start_new_session makes the PID the group ID, even if the leader exits
    # before we could call getpgid(). Never depend on descendant pipe EOF in
    # cleanup: close local descriptors after group termination and reaping.
    pgid = proc.pid
    selector = None
    deadline = time.monotonic() + timeout
    try:
        selector = selectors.DefaultSelector()
        for stream, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map() or proc.poll() is None:
            if cancellation_check is not None:
                cancellation_check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(
                    cmd=cmd, timeout=timeout,
                    output=text("stdout", errors="replace"), stderr=text("stderr", errors="replace"),
                )
            for key, _ in selector.select(timeout=min(0.05, remaining)):
                try:
                    chunk = os.read(key.fileobj.fileno(), min(_PIPE_READ_BYTES, max_output_bytes - captured_bytes + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if captured_bytes + len(chunk) > max_output_bytes:
                    raise SubprocessOutputLimitError(f"Subprocess output exceeded {max_output_bytes} bytes")
                output[key.data].extend(chunk)
                captured_bytes += len(chunk)
        return subprocess.CompletedProcess(cmd, proc.returncode, text("stdout"), text("stderr"))
    finally:
        # Also clean descendants that close their pipes and outlive a normally
        # exiting leader. No communicate() or blocking pipe reads here.
        try:
            kill_process_group(pgid, term_grace_seconds)
        finally:
            try:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=1.0)
            finally:
                if selector is not None:
                    selector.close()
                proc.stdout.close()
                proc.stderr.close()


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
