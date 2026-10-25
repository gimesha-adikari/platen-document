"""Small synthetic subprocess fixtures for the POSIX SDK boundary."""

from __future__ import annotations

import ctypes
import io
import locale
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from PIL import Image
import pytest

from platen_document.engine import _compat as compat
from platen_document.engine.adapters.tesseract import TesseractAdapter


pytestmark = pytest.mark.skipif(os.name != "posix", reason="existing process-group boundary requires POSIX")


def command(source: str) -> list[str]:
    return [sys.executable, "-u", "-c", source]


@pytest.fixture(autouse=True)
def tracked_processes(monkeypatch):
    processes = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(compat.subprocess, "Popen", start)
    yield processes
    for process in processes:
        try:
            assert process.poll() is not None, "direct child was not terminated/reaped"
            assert process.stdout.closed and process.stderr.closed, "capture descriptors leaked"
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


@pytest.mark.parametrize("stream", [1, 2])
def test_small_text_output(stream):
    completed = compat.run_hardened_subprocess(command(f"import os; os.write({stream}, b'hello\\n')"), timeout=3)
    assert completed.returncode == 0
    assert completed.stdout == ("hello\n" if stream == 1 else "")
    assert completed.stderr == ("hello\n" if stream == 2 else "")


def test_both_streams_above_pipe_capacity_complete():
    size = 256 * 1024
    completed = compat.run_hardened_subprocess(command(f"""
import os
import threading
barrier = threading.Barrier(2)
def write(fd, value):
    barrier.wait()
    os.write(fd, value * {size})
threads = [threading.Thread(target=write, args=(1, b'o')), threading.Thread(target=write, args=(2, b'e'))]
for thread in threads: thread.start()
for thread in threads: thread.join()
"""), timeout=3)
    assert completed.returncode == 0
    assert completed.stdout == "o" * size
    assert completed.stderr == "e" * size


def test_text_decoding_and_universal_newlines(monkeypatch):
    # Force split multibyte characters across individual pipe reads.
    monkeypatch.setattr(compat, "_PIPE_READ_BYTES", 1)
    encoding = "utf-8" if sys.flags.utf8_mode else locale.getencoding()
    text = "caf\u00e9\r\nline\rfinal\n"
    data = text.encode(encoding)
    completed = compat.run_hardened_subprocess(command(f"import os; os.write(1, {data!r}); os.write(2, {data!r})"), timeout=3)
    assert completed.stdout == completed.stderr == "caf\u00e9\nline\nfinal\n"
    assert isinstance(completed.stdout, str)


def test_invalid_text_still_raises_unicode_decode_error(monkeypatch):
    monkeypatch.setattr(compat.locale, "getencoding", lambda: "utf-8")
    with pytest.raises(UnicodeDecodeError):
        compat.run_hardened_subprocess(command("import os; os.write(1, b'\\xff')"), timeout=3)


def test_nonzero_exit_and_cwd_environment_contract(tmp_path):
    cmd = command("import os, sys; print(os.getcwd()); print(os.environ['F13_SYNTHETIC']); print('diagnostic', file=sys.stderr); sys.exit(7)")
    environment = dict(os.environ, F13_SYNTHETIC="synthetic-only")
    completed = compat.run_hardened_subprocess(cmd, timeout=3, cwd=str(tmp_path), env=environment)
    assert completed.args == cmd
    assert completed.returncode == 7
    assert completed.stdout.splitlines() == [str(tmp_path), "synthetic-only"]
    assert completed.stderr == "diagnostic\n"


def test_exact_combined_output_budget_succeeds():
    completed = compat.run_hardened_subprocess(command("import os; os.write(1, b'a' * 32); os.write(2, b'b' * 32)"), timeout=3, max_output_bytes=64)
    assert completed.stdout == "a" * 32
    assert completed.stderr == "b" * 32


@pytest.mark.parametrize("source", [
    "import os; os.write(1, b'x' * 4096)",
    "import os; os.write(2, b'x' * 4096)",
    "import os; os.write(1, b'x' * 40); os.write(2, b'y' * 40)",
])
def test_output_limit_is_combined_and_fails_promptly(source):
    started = time.monotonic()
    with pytest.raises(compat.SubprocessOutputLimitError, match="64 bytes"):
        compat.run_hardened_subprocess(command(source), timeout=4, term_grace_seconds=0.05, max_output_bytes=64)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("budget", [0, -1, float("inf"), float("nan"), 1.5, True])
def test_invalid_budget_rejects_before_start(budget, tracked_processes):
    with pytest.raises(ValueError):
        compat.run_hardened_subprocess(command("pass"), max_output_bytes=budget)
    assert not tracked_processes


@pytest.mark.parametrize("parameter", ["timeout", "term_grace_seconds"])
@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_deadline_rejects_before_start(parameter, value, tracked_processes):
    with pytest.raises(ValueError):
        compat.run_hardened_subprocess(command("pass"), **{parameter: value})
    assert not tracked_processes


def test_timeout_has_bounded_partial_text_and_reaps_child():
    cmd = command("import os, signal; os.write(1, b'prefix'); os.write(2, b'warning'); signal.pause()")
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as error:
        compat.run_hardened_subprocess(cmd, timeout=0.5, term_grace_seconds=0.05)
    assert error.value.cmd == cmd
    assert error.value.timeout == 0.5
    assert error.value.stdout == "prefix"
    assert error.value.stderr == "warning"
    assert time.monotonic() - started < 2


def test_timeout_is_not_masked_by_incomplete_unicode(monkeypatch):
    monkeypatch.setattr(compat.locale, "getencoding", lambda: "utf-8")
    with pytest.raises(subprocess.TimeoutExpired) as error:
        compat.run_hardened_subprocess(command("import os, signal; os.write(1, b'\\xc3'); signal.pause()"), timeout=0.5, term_grace_seconds=0.05)
    assert error.value.stdout == "\ufffd"


class SyntheticCancellation(Exception):
    pass


def test_cancellation_preserves_exception_and_reaps_child(tmp_path):
    ready = tmp_path / "ready"
    error = SyntheticCancellation("synthetic cancellation")

    def cancel():
        if ready.exists():
            raise error

    cmd = command(f"from pathlib import Path; import signal; Path({str(ready)!r}).touch(); signal.pause()")
    with pytest.raises(SyntheticCancellation) as result:
        compat.run_hardened_subprocess(cmd, timeout=3, term_grace_seconds=0.05, cancellation_check=cancel)
    assert result.value is error


def test_base_exception_cleanup(tmp_path):
    ready = tmp_path / "ready"

    def cancel():
        if ready.exists():
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        compat.run_hardened_subprocess(command(f"from pathlib import Path; import signal; Path({str(ready)!r}).touch(); signal.pause()"), timeout=3, term_grace_seconds=0.05, cancellation_check=cancel)


def test_cancellation_is_checked_while_output_is_continuously_ready(tmp_path):
    ready = tmp_path / "ready"

    def cancel():
        if ready.exists():
            raise SyntheticCancellation()

    cmd = command(f"from pathlib import Path; import os; Path({str(ready)!r}).touch()\nwhile True: os.write(1, b'x' * 32768)")
    with pytest.raises(SyntheticCancellation):
        compat.run_hardened_subprocess(cmd, timeout=3, term_grace_seconds=0.05, cancellation_check=cancel)


def test_pipe_registration_failure_cleans_child_and_descriptors(monkeypatch):
    class BrokenSelector:
        def register(self, *args):
            raise RuntimeError("synthetic registration failure")

        def close(self):
            pass

    monkeypatch.setattr(compat.selectors, "DefaultSelector", BrokenSelector)
    with pytest.raises(RuntimeError, match="registration failure"):
        compat.run_hardened_subprocess(command("import signal; signal.pause()"), timeout=3, term_grace_seconds=0.05)


@pytest.fixture
def descendants(tmp_path):
    if sys.platform != "linux":
        pytest.skip("descendant reaping fixture uses Linux subreaper support")
    # Adopt only this test's orphaned grandchildren and reap them, rather
    # than relying on the test host's PID 1 to reap killed fixture processes.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0  # PR_GET_CHILD_SUBREAPER
    assert libc.prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER
    pid_file = tmp_path / "descendant.pid"
    try:
        yield pid_file
    finally:
        if pid_file.exists():
            pid = int(pid_file.read_text())
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    if os.waitpid(pid, os.WNOHANG)[0] == pid:
                        break
                except ChildProcessError:
                    break
                time.sleep(0.01)
            else:
                pytest.fail("fixture descendant was not reaped")
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def tree_command(pid_file: Path, *, leader_exits: bool, inherit_pipes: bool = True, after_ready: str | None = None) -> list[str]:
    leaf = f"""
import os, signal
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path({str(pid_file)!r}).write_text(str(os.getpid()))
signal.pause()
"""
    return command(f"""
import subprocess, sys, time, signal
from pathlib import Path
subprocess.Popen([sys.executable, '-u', '-c', {leaf!r}],
                 stdout={'None' if inherit_pipes else 'subprocess.DEVNULL'},
                 stderr={'None' if inherit_pipes else 'subprocess.DEVNULL'})
while not Path({str(pid_file)!r}).exists(): time.sleep(0.005)
{after_ready if after_ready is not None else ('pass' if leader_exits else 'signal.pause()')}
""")


def assert_descendant_stopped(pid_file):
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            waited, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pid_file.unlink()
            return  # Already reaped by this fixture or its parent.
        if waited == pid:
            pid_file.unlink()
            return
        time.sleep(0.01)
    pytest.fail("descendant survived group cleanup")


@pytest.mark.parametrize("leader_exits", [False, True])
def test_timeout_escalates_and_never_waits_for_descendant_pipe_eof(descendants, leader_exits):
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        compat.run_hardened_subprocess(tree_command(descendants, leader_exits=leader_exits), timeout=0.7, term_grace_seconds=0.05)
    assert time.monotonic() - started < 2
    assert_descendant_stopped(descendants)


def test_cancellation_escalates_after_leader_exit(descendants):
    def cancel():
        if descendants.exists():
            raise SyntheticCancellation()

    with pytest.raises(SyntheticCancellation):
        compat.run_hardened_subprocess(tree_command(descendants, leader_exits=True), timeout=3, term_grace_seconds=0.05, cancellation_check=cancel)
    assert_descendant_stopped(descendants)


def test_output_limit_terminates_group_and_resistant_descendant(descendants):
    cmd = tree_command(descendants, leader_exits=False, after_ready="sys.stdout.write('x' * 4096); sys.stdout.flush(); signal.pause()")
    with pytest.raises(compat.SubprocessOutputLimitError):
        compat.run_hardened_subprocess(cmd, timeout=3, term_grace_seconds=0.05, max_output_bytes=64)
    assert_descendant_stopped(descendants)


def test_success_cleans_descendants_that_closed_capture_pipes(descendants):
    result = compat.run_hardened_subprocess(tree_command(descendants, leader_exits=True, inherit_pipes=False), timeout=3, term_grace_seconds=0.05)
    assert result.returncode == 0
    assert_descendant_stopped(descendants)


def test_repeated_calls_do_not_leak_descriptors():
    descriptors = Path("/proc/self/fd")
    if not descriptors.is_dir():
        pytest.skip("descriptor accounting uses procfs")
    before = len(list(descriptors.iterdir()))
    for _ in range(8):
        assert compat.run_hardened_subprocess(command("print('ok')"), timeout=3).stdout == "ok\n"
    assert len(list(descriptors.iterdir())) == before


@pytest.mark.parametrize("consumer", ["probe", "recognize"])
@pytest.mark.parametrize("exit_code", [0, 3])
def test_tesseract_receives_compatible_text_and_removes_input(monkeypatch, consumer, exit_code):
    image_paths = []
    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t10\t20\t10\t90\tSynthetic\n"
    from platen_document.engine.adapters import tesseract

    def substitute(cmd, **kwargs):
        image_paths.append(Path(cmd[1]))
        assert image_paths[-1].exists()
        return compat.run_hardened_subprocess(command(f"import sys; print({tsv!r}, end=''); print('synthetic diagnostic', file=sys.stderr); sys.exit({exit_code})"), **kwargs)

    monkeypatch.setattr(tesseract, "run_hardened_subprocess", substitute)
    adapter = TesseractAdapter("eng")
    image = Image.new("RGB", (64, 32))
    if consumer == "probe":
        probe = adapter.probe(image, ("eng",))
        assert probe.text == ("Synthetic" if exit_code == 0 else "")
        assert probe.confidence == (90 if exit_code == 0 else -1)
    else:
        from platen_document.engine.contracts import PageGeometry
        from platen_document.engine.errors import EngineUnavailableError
        from platen_document.engine.geometry import PreparedRaster

        monkeypatch.setattr(adapter, "readiness", lambda: True)
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        raster = PreparedRaster(image, encoded.getvalue(), PageGeometry(64, 32), 72)
        if exit_code:
            with pytest.raises(EngineUnavailableError, match="synthetic diagnostic"):
                adapter.recognize_page("page-1", raster)
        else:
            result = adapter.recognize_page("page-1", raster)
            assert result.text == "Synthetic"
            assert result.raw_output == {"tsv": tsv}
    assert all(not path.exists() for path in image_paths)
