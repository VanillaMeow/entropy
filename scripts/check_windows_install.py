"""Check GUI worker startup and uninstall confirmation on a clean Windows build host."""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

UI_INSPECTOR = """param($ProcessName, $Action)
Add-Type -AssemblyName UIAutomationClient
$ids = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue).Id
$root = [System.Windows.Automation.AutomationElement]::RootElement
$scope = [System.Windows.Automation.TreeScope]::Descendants
$condition = [System.Windows.Automation.Condition]::TrueCondition
$elements = @($root.FindAll($scope, $condition) | Where-Object {
    $ids -contains $_.Current.ProcessId
})
if ($Action) {
    $button = $elements | Where-Object {
        $_.Current.Name.Replace('&', '') -eq $Action
    } | Select-Object -First 1
    if ($button) {
        $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        Start-Sleep -Milliseconds 300
        $elements = @($root.FindAll($scope, $condition) | Where-Object {
            $ids -contains $_.Current.ProcessId
        })
    }
}
$items = @($elements | ForEach-Object {
    $value = ''
    $pattern = $null
    if ($_.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
        $value = $pattern.Current.Value
    }
    [PSCustomObject]@{ Name = $_.Current.Name; Value = $value }
})
ConvertTo-Json -InputObject $items -Compress
"""


def run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Capture child diagnostics and fail on a nonzero exit code."""
    print(f"Running: {command}", flush=True)
    result = subprocess.run(
        command, capture_output=True, text=True, errors="replace", timeout=timeout
    )
    print(f"Exit code: {result.returncode}\n{result.stdout}\n{result.stderr}", flush=True)
    result.check_returncode()
    return result


def inspect_ui(script: Path, name: str, action: str = "") -> list[dict[str, str]]:
    """Read only the tested application's accessible controls and diagnostics."""
    result = run(["powershell", "-NoProfile", "-File", str(script), name, action])
    return json.loads(result.stdout)


def check_worker(application: Path, script: Path, log: Path) -> None:
    """Require a worker handshake through the installed GUI's real QProcess."""
    with log.open("w+", encoding="utf-8") as output:
        process = subprocess.Popen(
            [str(application)],
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.DETACHED_PROCESS,
        )
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Installed application exited with {process.returncode}.")
                controls = inspect_ui(script, "Entropy", "Open diagnostics")
                diagnostics = "\n".join(item["Value"] for item in controls)
                if "GPU runtime:" in diagnostics:
                    # Hosted runners need to load MNN, but do not have an OpenCL GPU.
                    print("Installed GUI received the MNN worker handshake.", flush=True)
                    return
                if "crashed" in diagnostics or "failed to start" in diagnostics:
                    raise RuntimeError(diagnostics)
                time.sleep(1)
            raise RuntimeError(
                "Installed GUI did not receive the worker handshake within 45 seconds."
            )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            output.seek(0)
            print(f"Application log:\n{output.read()}", flush=True)


def registered_uninstaller(target: Path) -> str | None:
    """Find the exact per-user Windows Settings entry created by this installation."""
    import winreg

    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as entries:
        for index in range(winreg.QueryInfoKey(entries)[0]):
            with winreg.OpenKey(entries, winreg.EnumKey(entries, index)) as entry:
                values = {
                    name: value
                    for name, value, _ in (
                        winreg.EnumValue(entry, i) for i in range(winreg.QueryInfoKey(entry)[1])
                    )
                }
                if Path(values.get("InstallLocation", "")).resolve() == target:
                    return values.get("UninstallString")
    return None


def check_uninstall_confirmation(target: Path, script: Path) -> None:
    """Launch the registered uninstaller through the shell, then cancel removal."""
    maintenance = target / "EntropyMaintenanceTool.exe"
    command = registered_uninstaller(target)
    if command is None or command.strip('"').casefold() != str(maintenance).casefold():
        raise RuntimeError(f"Incorrect Windows Settings uninstall command: {command}")
    print(f"Windows Settings uninstall command: {command}", flush=True)
    os.startfile(str(maintenance), cwd=str(Path(os.environ["WINDIR"]) / "System32"))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        controls = inspect_ui(script, "EntropyMaintenanceTool")
        if any(item["Name"].replace("&", "") == "Uninstall" for item in controls):
            break
        time.sleep(1)
    else:
        raise RuntimeError("Registered uninstaller did not show its removal confirmation.")
    inspect_ui(script, "EntropyMaintenanceTool", "Cancel")
    inspect_ui(script, "EntropyMaintenanceTool", "Yes")
    if inspect_ui(script, "EntropyMaintenanceTool"):
        raise RuntimeError("Uninstall cancellation did not close the maintenance window.")
    if not (target / "app" / "Entropy.exe").is_file():
        raise RuntimeError("Cancelling uninstall removed the application.")
    print("Uninstall confirmation and cancellation passed.", flush=True)


def main() -> int:
    """Install the package, check both GUI paths, and verify confirmed removal."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    installer = parser.parse_args().installer.resolve()
    with tempfile.TemporaryDirectory(prefix="entropy install ") as temporary:
        root = Path(temporary).resolve()
        script = root / "inspect-ui.ps1"
        script.write_text(UI_INSPECTOR, encoding="utf-8")
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
        )
        failures = []
        for check in (
            lambda: check_worker(target / "app" / "Entropy.exe", script, root / "application.log"),
            lambda: check_uninstall_confirmation(target, script),
        ):
            try:
                check()
            except (RuntimeError, subprocess.SubprocessError) as exc:
                failures.append(str(exc))
                print(f"FAILED: {exc}", flush=True)
        # Ensure failed GUI checks cannot keep the maintenance data locked during cleanup.
        run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$entropyProcesses = @(Get-Process EntropyMaintenanceTool "
                "-ErrorAction SilentlyContinue); "
                "foreach ($entropyProcess in $entropyProcesses) { "
                "Stop-Process -Id $entropyProcess.Id -ErrorAction Stop }; exit 0",
            ]
        )
        run([str(target / "EntropyMaintenanceTool.exe"), "--confirm-command", "purge"])
        if (target / "app" / "Entropy.exe").exists() or registered_uninstaller(target):
            raise RuntimeError(
                "Confirmed uninstall left the application or Windows Settings entry."
            )
        if failures:
            raise RuntimeError("\n".join(failures))
        print("Installed worker, uninstall cancellation, and confirmed removal passed.", flush=True)
    return 0


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This check requires Windows.")
    raise SystemExit(main())
