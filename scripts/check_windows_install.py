"""Exercise the installed Windows worker and maintenance tool on a clean host."""

import argparse
import json
import os
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
                    "$all | ForEach-Object { $_.Current } | "
                    "Select-Object ProcessId,Name,AutomationId | ConvertTo-Json -Compress",
                ]
            )
            gui.terminate()
            gui.wait(timeout=10)
            output.seek(0)
            print(f"Application diagnostics:\n{output.read()}", flush=True)
        maintenance = target / "EntropyMaintenanceTool.exe"
        packages = run([str(maintenance), "--verbose", "list"])
        subprocess.Popen(
            [str(maintenance)],
            cwd=Path(os.environ["WINDIR"]) / "System32",
            creationflags=subprocess.DETACHED_PROCESS,
        )
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
