"""Exercise the installed Windows worker and maintenance tool on a clean host."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Capture child diagnostics even when a packaged executable fails."""
    print(f"Running: {command}", flush=True)
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    print(f"Exit code: {result.returncode}\n{result.stdout}\n{result.stderr}", flush=True)
    return result


def main() -> int:
    """Install the release, record worker errors, and check maintenance startup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    installer = parser.parse_args().installer.resolve()
    with tempfile.TemporaryDirectory(prefix="entropy install ") as temporary:
        root = Path(temporary).resolve()
        target = root / "Entropy"
        run(
            [
                str(installer),
                "--root",
                str(target),
                "--accept-licenses",
                "--confirm-command",
                "--default-answer",
                "install",
            ]
        ).check_returncode()
        application = target / "app" / "Entropy.exe"
        worker = run([str(application), "--worker", "--prepare"])
        detached_result = root / "detached-worker.json"
        helper = root / "detached-worker.py"
        helper.write_text(
            "import json, subprocess, sys\n"
            "from pathlib import Path\n"
            "r = subprocess.run([sys.argv[1], '--worker', '--prepare'], "
            "capture_output=True, text=True, timeout=60)\n"
            "Path(sys.argv[2]).write_text(json.dumps({"
            "'code': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}))\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(helper), str(application), str(detached_result)],
            creationflags=subprocess.DETACHED_PROCESS,
            check=True,
            timeout=90,
        )
        print(f"Worker without a parent console: {detached_result.read_text()}", flush=True)
        qt_helper = root / "qt-worker.py"
        qt_result = root / "qt-worker.json"
        qt_helper.write_text(
            "import json, sys\n"
            "from pathlib import Path\n"
            "from PySide6.QtCore import QCoreApplication, QProcess, QTimer\n"
            "app = QCoreApplication([])\n"
            "p = QProcess()\n"
            "def finished(code, status):\n"
            "    Path(sys.argv[2]).write_text(json.dumps({'code': code, 'status': str(status), "
            "'stdout': bytes(p.readAllStandardOutput()).decode(errors='replace'), "
            "'stderr': bytes(p.readAllStandardError()).decode(errors='replace'), "
            "'error': p.errorString()}))\n"
            "    app.quit()\n"
            "p.finished.connect(finished)\n"
            "p.start(sys.argv[1], ['--worker', '--prepare'])\n"
            "QTimer.singleShot(60000, app.quit)\n"
            "app.exec()\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(qt_helper), str(application), str(qt_result)],
            creationflags=subprocess.DETACHED_PROCESS,
            check=True,
            timeout=90,
        )
        print(f"Worker launched by QProcess: {qt_result.read_text()}", flush=True)
        if os.environ.get("ENTROPY_TEST_REPAIR_WORKER") == "true":
            # Diagnostic fixture only: Nuitka points sys.executable at a missing python.exe.
            shutil.copy2(application, application.with_name("python.exe"))
        trace_script = root / "trace.ps1"
        trace_ready = root / "trace.ready"
        trace_file = root / "trace.json"
        trace_script.write_text(
            "param($Ready, $Result)\n"
            "Register-CimIndicationEvent -ClassName Win32_ProcessStartTrace "
            "-SourceIdentifier EntropyStart | Out-Null\n"
            "Register-CimIndicationEvent -ClassName Win32_ProcessStopTrace "
            "-SourceIdentifier EntropyStop | Out-Null\n"
            "Set-Content $Ready ready\n"
            "Start-Sleep 20\n"
            "Get-Event | ForEach-Object { $_.SourceEventArgs.NewEvent } | "
            "Where-Object { $_.ProcessName -eq 'Entropy.exe' } | "
            "Select-Object ProcessName,ProcessID,ParentProcessID,ExitStatus | "
            "ConvertTo-Json | Set-Content $Result\n",
            encoding="utf-8",
        )
        trace = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-File",
                str(trace_script),
                str(trace_ready),
                str(trace_file),
            ]
        )
        for _ in range(100):
            if trace_ready.exists():
                break
            time.sleep(0.1)
        gui_log = root / "application.log"
        with gui_log.open("w+", encoding="utf-8") as output:
            gui = subprocess.Popen(
                [str(application)],
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.DETACHED_PROCESS,
            )
            time.sleep(10)
            run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Add-Type -AssemblyName UIAutomationClient; "
                    "$root = [System.Windows.Automation.AutomationElement]::RootElement; "
                    "$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, "
                    "[System.Windows.Automation.Condition]::TrueCondition); "
                    "$button = $all | Where-Object { $_.Current.Name -eq 'Open diagnostics' } | "
                    "Select-Object -First 1; "
                    "if ($button) { $button.GetCurrentPattern("
                    "[System.Windows.Automation.InvokePattern]::Pattern).Invoke(); "
                    "Start-Sleep 1 }; "
                    "$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, "
                    "[System.Windows.Automation.Condition]::TrueCondition); "
                    "$all | ForEach-Object { "
                    "try { $_.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)"
                    ".Current.Value } catch {} }; "
                    "$all | ForEach-Object { $_.Current } | "
                    "Select-Object ProcessId,Name,AutomationId | ConvertTo-Json -Compress",
                ]
            )
            gui.terminate()
            gui.wait(timeout=10)
            output.seek(0)
            print(f"Application diagnostics:\n{output.read()}", flush=True)
        trace.wait(timeout=30)
        print(f"Windows process events: {trace_file.read_text()}", flush=True)
        run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-WinEvent -FilterHashtable @{LogName='Application'; Level=2; "
                "StartTime=(Get-Date).AddMinutes(-5)} -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,ProviderName,Message | ConvertTo-Json",
            ]
        )
        maintenance = target / "EntropyMaintenanceTool.exe"
        packages = run([str(maintenance), "--verbose", "list"])
        os.startfile(str(maintenance), cwd=str(Path(os.environ["WINDIR"]) / "System32"))
        time.sleep(10)
        run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process EntropyMaintenanceTool -ErrorAction SilentlyContinue | "
                "Select-Object Id,MainWindowTitle,Path | ConvertTo-Json; "
                "Get-Process EntropyMaintenanceTool -ErrorAction SilentlyContinue | Stop-Process",
            ]
        )
        with (root / "maintenance.log").open("w+", encoding="utf-8") as output:
            process = subprocess.Popen(
                [str(maintenance), "--verbose"], stdout=output, stderr=subprocess.STDOUT
            )
            try:
                code = process.wait(timeout=10)
                print(f"Maintenance GUI exited early: {code}", flush=True)
            except subprocess.TimeoutExpired:
                print("Maintenance GUI remains open.", flush=True)
                process.terminate()
                process.wait(timeout=10)
                code = 0
            output.seek(0)
            print(output.read(), flush=True)
        run([str(maintenance), "--confirm-command", "purge"]).check_returncode()
        return int(
            worker.returncode != 0
            or json.loads(detached_result.read_text())["code"] != 0
            or packages.returncode != 0
            or code != 0
        )


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This check requires Windows.")
    raise SystemExit(main())
