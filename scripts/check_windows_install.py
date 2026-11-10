"""Exercise the installed Windows worker and maintenance tool on a clean host."""

import argparse
import os
import subprocess
import tempfile
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
        worker = run([str(application), "--worker", "--probe"])
        maintenance = target / "EntropyMaintenanceTool.exe"
        packages = run([str(maintenance), "--verbose", "list"])
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
        return int(worker.returncode != 0 or packages.returncode != 0 or code != 0)


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This check requires Windows.")
    raise SystemExit(main())
