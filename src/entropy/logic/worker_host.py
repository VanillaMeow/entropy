"""Run the inference worker as a child process and relay its typed events."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError
from PySide6.QtCore import QCoreApplication, QObject, QProcess, QTimer, Signal

from entropy.core.events import Error, ModelReady, decode
from entropy.paths import is_compiled

if TYPE_CHECKING:
    from entropy.core.config import UpscaleRequest

type WorkerMode = Literal['probe', 'prepare', 'job']

# Generous enough for a cold driver, short enough to surface a hung probe
PROBE_TIMEOUT_MS = 30_000

# How long closing the window waits for a killed worker to exit
SHUTDOWN_WAIT_MS = 3000


class WorkerHost(QObject):
    """Stream worker events without running native inference in the UI process.

    ``received`` carries a ``WorkerEvent``, ``diagnostic`` carries log text and
    ``finished`` carries the exit code and whether the run was cancelled.
    """

    received = Signal(object)
    diagnostic = Signal(str)
    finished = Signal(int, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # State of the current run, reset by start()
        self._process: QProcess | None = None
        self._mode: WorkerMode | None = None
        self._buffer = b''
        self._cancelled = False
        self._timed_out = False

        # Only GPU probes are timed, a batch may legitimately run for hours
        self._probe_timeout = QTimer(self)
        self._probe_timeout.setSingleShot(True)
        self._probe_timeout.timeout.connect(self._timeout)

    @property
    def running(self) -> bool:
        """Whether a worker process is currently owned by this host."""
        return self._process is not None

    def start(self, mode: WorkerMode, request: UpscaleRequest | None = None) -> None:
        """Start a probe, a model setup, or a batch job read by the worker from stdin."""
        if self.running:
            msg = 'A worker is already running.'
            raise RuntimeError(msg)

        if (mode == 'job') != (request is not None):
            msg = 'A request is required for a job and only for a job.'
            raise ValueError(msg)

        self._mode = mode
        self._buffer = b''
        self._cancelled = False
        self._timed_out = False

        process = QProcess(self)
        self._process = process
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)

        # The compiled app is its own worker, from source the package runs under Python
        if is_compiled():
            process.start(QCoreApplication.applicationFilePath(), ['--worker', f'--{mode}'])
        else:
            process.start(sys.executable, ['-u', '-m', 'entropy', '--worker', f'--{mode}'])

        # QProcess buffers the request until the child starts, closing stdin ends it
        if request is not None:
            process.write(request.model_dump_json().encode())
        process.closeWriteChannel()

        if mode == 'probe':
            self._probe_timeout.start(PROBE_TIMEOUT_MS)

    def cancel(self) -> None:
        """Kill the isolated worker, including a blocked native GPU call."""
        if self._process is not None:
            self._cancelled = True
            self._process.kill()

    def shutdown(self) -> None:
        """Reap the child before closing the desktop window."""
        process = self._process
        if process is not None:
            self.cancel()
            process.waitForFinished(SHUTDOWN_WAIT_MS)

    def _read_stdout(self) -> None:
        """Turn complete stdout lines into events, and everything else into diagnostics."""
        if self._process is None:
            return

        # Output arrives in arbitrary chunks, so keep any unfinished line for next time
        self._buffer += bytes(self._process.readAllStandardOutput().data())
        while b'\n' in self._buffer:
            raw, self._buffer = self._buffer.split(b'\n', 1)
            line = raw.decode(errors='replace')

            try:
                event = decode(line)
            except ValidationError:
                self.diagnostic.emit(f'Invalid worker event: {line}')
                continue

            # Not an event, so it is MNN's or Python's own output
            if event is None:
                if line.strip():
                    self.diagnostic.emit(line)
                continue

            # A setup run only starts its GPU probe once the model is in place
            if self._mode == 'prepare' and isinstance(event, ModelReady):
                self._probe_timeout.start(PROBE_TIMEOUT_MS)

            self.received.emit(event)

    def _read_stderr(self) -> None:
        if self._process is not None:
            text = bytes(self._process.readAllStandardError().data()).decode(errors='replace')
            self.diagnostic.emit(text)

    def _timeout(self) -> None:
        self._timed_out = True
        seconds = PROBE_TIMEOUT_MS // 1000
        self.received.emit(Error(message=f'GPU setup check timed out after {seconds} seconds.'))

        if self._process is not None:
            self._process.kill()

    def _on_error(self, error: QProcess.ProcessError) -> None:
        # Every other error is followed by finished(), which handles it there
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self.received.emit(Error(message=self._process.errorString()))
            self._finish(-1)

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        if self._process is None:
            return

        # Drain whatever the worker wrote right before exiting
        self._read_stdout()
        self._read_stderr()

        # A kill we asked for also counts as a crash, but is not one to report
        crashed = status == QProcess.ExitStatus.CrashExit
        if crashed and not self._cancelled and not self._timed_out:
            self.received.emit(Error(message='The native MNN worker crashed. See details below.'))

        self._finish(code)

    def _finish(self, code: int) -> None:
        process = self._process
        if process is None:
            return

        self._probe_timeout.stop()
        self._process = None
        process.deleteLater()
        self.finished.emit(code, self._cancelled)
