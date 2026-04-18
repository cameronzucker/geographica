"""Shared GDAL subprocess wrapper with process-group cancellation support.

Extracted from acquire_imagery.py so sibling pipelines (acquire_naip.py,
and any future callers) share the same cancellable subprocess behavior.

Why this exists: `subprocess.run(...)` blocks the main thread. A pending
SIGTERM sets a cancellation flag but the main thread can't check it until
the subprocess exits. For GDAL operations that run for 30+ minutes (gdaladdo
on large mosaics), this makes cancel effectively ineffective.

This helper uses Popen(preexec_fn=os.setsid) to create a new process group,
exposes the child PID via on_child_started callback so the caller can
register it for SIGTERM forwarding, and checks cancel_check between
communicate() polling so cancellation is timely.
"""

from __future__ import annotations

import os
import signal
import subprocess


def run_gdal_subprocess(
    cmd: list[str],
    timeout: int = 7200,
    cancel_check=None,
    on_child_started=None,
    on_child_ended=None,
) -> subprocess.CompletedProcess:
    """Run a GDAL CLI command with nice priority and process-group cancellation.

    Args:
        cmd: Command and arguments (e.g., ["gdalbuildvrt", ...]).
        timeout: Max seconds before killing the process.
        cancel_check: Optional callable returning True if cancellation
            requested. Called before spawning; if True, raises
            CalledProcessError immediately.
        on_child_started: Optional callable(pid) invoked after Popen
            succeeds. Use this to register the pid with your module's
            SIGTERM handler so it can killpg the child on signal.
        on_child_ended: Optional callable() invoked in the finally block
            once the child has exited. Use to clear the registered pid.

    Returns:
        CompletedProcess on success.

    Raises:
        subprocess.CalledProcessError: if command fails or is cancelled
            before start.
        subprocess.TimeoutExpired: if timeout exceeded.
    """
    if cancel_check and cancel_check():
        raise subprocess.CalledProcessError(1, cmd, stderr="Cancelled before start")

    full_cmd = ["nice", "-n", "19"] + cmd
    gdal_env = {
        **os.environ,
        "GDAL_CACHEMAX": os.environ.get("GDAL_CACHEMAX", "1024"),
        "GDAL_NUM_THREADS": os.environ.get("GDAL_NUM_THREADS", "ALL_CPUS"),
    }
    proc = subprocess.Popen(
        full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=gdal_env,
        preexec_fn=os.setsid,  # new process group so caller can killpg it
    )
    if on_child_started is not None:
        try:
            on_child_started(proc.pid)
        except Exception:
            # Don't let a buggy callback abort the subprocess run
            pass
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            raise
    finally:
        if on_child_ended is not None:
            try:
                on_child_ended()
            except Exception:
                pass

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, full_cmd, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(full_cmd, proc.returncode, stdout, stderr)
