"""Exercise the real offline EXE with isolated settings and invented archived history."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def wait_for(predicate):
    for _ in range(100):
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Packaged tray lifecycle timed out.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="AgentTelemetry offline install ") as directory:
        root = Path(directory).resolve()
        app = root / "Application with spaces"
        local = root / "Local AppData"
        support = local / "AgentTelemetryNative"
        ledger = local / "AgentTelemetry" / ".usage_cache.json"
        ledger.parent.mkdir(parents=True)
        fixture = b'{"version":53,"files":{"invented":{"archived":true,"fixture":true}}}'
        ledger.write_bytes(fixture)
        environment = dict(os.environ, LOCALAPPDATA=str(local),
                           APPDATA=str(root / "Roaming"), PYTHONDONTWRITEBYTECODE="1")
        arguments = [str(args.installer.resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                     "/NORESTART", "/DIR=" + str(app)]

        def install():
            return subprocess.run(arguments, env=environment, timeout=90)

        assert install().returncode == 0, "Clean offline install failed."
        assert ledger.read_bytes() == fixture
        python = app / "runtime" / "python.exe"
        pythonw = app / "runtime" / "pythonw.exe"
        entry = app / "windows" / "tray.py"
        manifest = json.loads((support / "native-install.json").read_text())
        assert len(manifest["command"]) == 2
        assert Path(manifest["command"][0]).samefile(pythonw)
        assert Path(manifest["command"][1]).samefile(entry)
        assert manifest["version"] == args.expected_version
        info = json.loads((app / "BUILD-INFO.json").read_text())
        assert info["commit"] == args.expected_commit
        subprocess.run([str(python), "-c", "import ctypes, sqlite3, ssl, urllib.request, dashboard; assert dashboard.CACHE_VERSION in (53, 54, 55)"],
                       env=environment, check=True, timeout=30)
        subprocess.run([str(python), str(entry), "--self-test"],
                       env=environment, check=True, timeout=30)
        assert not (support / "tray-settings.json").exists(), "Install enabled a persistent startup option."
        assert install().returncode == 0, "Upgrade failed."
        assert ledger.read_bytes() == fixture
        tray = subprocess.Popen([str(pythonw), str(entry)], env=environment)
        try:
            wait_for(lambda: (support / "native-status.json").exists())
            assert install().returncode != 0, "Installer replaced a running tray client."
            assert ledger.read_bytes() == fixture
        finally:
            control = support / "native-control.json"
            if control.exists():
                value = json.loads(control.read_text())
                value["enabled"] = False
                temporary = support / "test-control.tmp"
                temporary.write_text(json.dumps(value))
                os.replace(temporary, control)
            tray.wait(timeout=30)
        assert install().returncode == 0, "Upgrade after graceful Quit failed."
        subprocess.run([str(app / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       env=environment, check=True, timeout=60)
        assert ledger.read_bytes() == fixture, "Uninstall changed usage history."
        assert not entry.exists()
        assert json.loads((support / "native-install.json").read_text()) == {}
        print("PASS offline EXE install, bundled runtime/Win32 UI, running-app guard, upgrade and uninstall preserve archived telemetry.")


if __name__ == "__main__":
    main()
