"""Register the binary install; usage history is never modified."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[2] if SCRIPT.parent.name == "installer" else SCRIPT.parents[1]
sys.path.insert(0, str(ROOT))
import native


def manifest():
    entry = ROOT / "windows" / "tray.py"
    pythonw = ROOT / "runtime" / "pythonw.exe"
    if not entry.is_file() or not pythonw.is_file():
        raise ValueError("The application or bundled Python is missing. Reinstall AgentTelemetry.")
    version = json.loads((ROOT / "BUILD-INFO.json").read_text(encoding="utf-8"))["version"]
    return {"platform": "win32", "entry": str(entry),
            "command": [str(pythonw), str(entry)], "version": version}


def update_login(previous, current):
    """Preserve an existing opt-in only when its command belongs to this app."""
    import winreg
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, "AgentTelemetry")
            command = previous.get("command")
            if isinstance(command, list) and command and value == subprocess.list2cmdline(command):
                if current is None:
                    winreg.DeleteValue(key, "AgentTelemetry")
                else:
                    winreg.SetValueEx(key, "AgentTelemetry", 0, winreg.REG_SZ,
                                      subprocess.list2cmdline(current["command"]))
    except FileNotFoundError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "register", "unregister", "launch"))
    args = parser.parse_args()
    try:
        if args.operation == "check":
            return 10 if native.status()["running"] else 0
        if args.operation == "launch":
            native.action(True)
            return 0
        if native.status()["running"]:
            raise ValueError("Quit AgentTelemetry and wait for its ledger save before updating or uninstalling.")
        previous = native._read("native-install.json")
        if args.operation == "register":
            current = manifest()
            update_login(previous, current)
            native._write("native-install.json", current)
        elif previous.get("entry") == str(ROOT / "windows" / "tray.py"):
            update_login(previous, None)
            native._write("native-install.json", {})
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
