"""Qt integration for the disposable MNN worker process."""

import json
import sys
from typing import Any

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .worker import EVENT_PREFIX


class WorkerProcess(QObject):
    """Stream worker events without running native inference in the UI process."""

    event = Signal(dict)
    diagnostic = Signal(str)
    finished = Signal(int, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._buffer = b""
        self._cancelled = False
        self._timed_out = False
        self._preparing = False
        self._probe_timeout = QTimer(self)
        self._probe_timeout.setSingleShot(True)
        self._probe_timeout.timeout.connect(self._timeout)

    @property
    def running(self) -> bool:
        """Whether a worker is currently owned by this controller."""
        return self._process is not None

    def start(self, argument: str) -> None:
        """Start one probe or JSON job; concurrent starts are a programming error."""
        if self.running:
            raise RuntimeError("A worker is already running.")
        self._buffer = b""
        self._cancelled = False
        self._timed_out = False
        self._preparing = argument == "--prepare"
        process = QProcess(self)
        self._process = process
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        process.start(sys.executable, ["-u", "-m", f"{__package__}.worker", argument])
        if argument == "--probe":
            self._probe_timeout.start(30000)

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
            process.waitForFinished(3000)

    def _read_stdout(self) -> None:
        if self._process is None:
            return
        self._buffer += bytes(self._process.readAllStandardOutput())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            decoded = line.decode("utf-8", errors="replace")
            if decoded.startswith(EVENT_PREFIX):
                try:
                    payload: Any = json.loads(decoded[len(EVENT_PREFIX) :])
                except json.JSONDecodeError:
                    self.diagnostic.emit(f"Invalid worker event: {decoded}")
                    continue
                if isinstance(payload, dict):
                    if self._preparing and payload.get("event") == "model_ready":
                        self._probe_timeout.start(30000)
                    self.event.emit(payload)
            elif decoded.strip():
                self.diagnostic.emit(decoded)

    def _timeout(self) -> None:
        self._timed_out = True
        self.event.emit(
            {"event": "error", "message": "GPU backend check timed out after 30 seconds."}
        )
        if self._process is not None:
            self._process.kill()

    def _read_stderr(self) -> None:
        if self._process is not None:
            self.diagnostic.emit(
                bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
            )

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self.event.emit({"event": "error", "message": self._process.errorString()})
            self._on_finished(-1, QProcess.ExitStatus.CrashExit)

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        process = self._process
        if process is None:
            return
        self._probe_timeout.stop()
        self._read_stdout()
        self._read_stderr()
        if status == QProcess.ExitStatus.CrashExit and not self._cancelled and not self._timed_out:
            self.event.emit(
                {"event": "error", "message": "The native MNN worker crashed. See details below."}
            )
        self._process = None
        process.deleteLater()
        self.finished.emit(code, self._cancelled)
