"""Local TCP listener inventory and short-lived history for the dashboard."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import getpass
import threading
import time
from datetime import datetime, timedelta, timezone

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt below
    fcntl = None


_LSOF = shutil.which("lsof") or "/usr/sbin/lsof"
_PS = shutil.which("ps") or "/bin/ps"
_HISTORY_DAYS = 30
_MAX_SERVERS = 100
_PORT_RE = re.compile(r"^(.*):(\d+)$")
_PROFILE_START_LOCKS = {}
_PROFILE_START_LOCKS_GUARD = threading.Lock()


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def _parse_stamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def _server_id(pid, started_at, port):
    identity = f"{int(pid)}:{str(started_at).strip()}:{int(port)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _profile_id(cwd, port):
    directory = os.path.realpath(os.path.expanduser(str(cwd).strip()))
    identity = f"{directory}:{int(port)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _uses_running_port(server, port):
    try:
        return server.get("state") == "running" and int(server.get("port")) == port
    except (AttributeError, TypeError, ValueError):
        return False


def _is_local_server(item):
    """Keep project/service listeners; omit OS processes running from /."""
    cwd = item.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return False
    cwd = os.path.normpath(os.path.expanduser(cwd.strip()))
    if cwd == os.path.sep or cwd.startswith(("/System/", "/Library/")):
        return False
    return True


@contextlib.contextmanager
def _inventory_lock(path):
    with open(path, "a+b") as lock:
        try:
            os.fchmod(lock.fileno(), 0o600)
        except (AttributeError, OSError):
            pass
        if fcntl is not None:
            fcntl.lockf(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.lockf(lock.fileno(), fcntl.LOCK_UN)
        elif os.name == "nt":
            import msvcrt
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            yield


@contextlib.contextmanager
def _profile_start_lock(path):
    with _PROFILE_START_LOCKS_GUARD:
        lock = _PROFILE_START_LOCKS.setdefault(path, threading.Lock())
    with lock:
        with _inventory_lock(path):
            yield


def _run(arguments):
    try:
        return subprocess.run(
            arguments, check=False, capture_output=True, text=True,
            timeout=8, env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _process_start_times(pids):
    if not pids:
        return {}
    result = _run([_PS, "-p", ",".join(str(pid) for pid in sorted(pids)), "-o", "pid=,lstart="])
    if result is None:
        return {}
    starts = {}
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2:
            try:
                starts[int(fields[0])] = fields[1]
            except ValueError:
                continue
    return starts


def _working_directories(uid):
    result = _run([_LSOF, "-a", "-u", str(uid), "-d", "cwd", "-Fpn"])
    if result is None:
        return {}
    pid = None
    paths = {}
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
            except ValueError:
                pid = None
        elif line.startswith("n") and pid is not None:
            paths[pid] = line[1:]
    return paths


def _listener_rows(uid):
    result = _run([
        _LSOF, "-a", "-u", str(uid), "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn",
    ])
    if result is None:
        raise RuntimeError("Could not inspect local listening ports.")

    processes = {}
    pid = None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
                processes.setdefault(pid, {"process": "", "endpoints": set()})
            except ValueError:
                pid = None
        elif pid is not None and line.startswith("c"):
            processes[pid]["process"] = line[1:]
        elif pid is not None and line.startswith("n"):
            match = _PORT_RE.match(line[1:])
            if match:
                host, port = match.groups()
                processes[pid]["endpoints"].add((host.strip("[]"), int(port)))

    starts = _process_start_times(processes)
    if processes and not starts:
        raise RuntimeError("Could not identify the start time of local listener processes.")
    cwd_by_pid = _working_directories(uid)
    rows = {}
    for process_id, data in processes.items():
        if process_id == os.getpid():
            continue
        started_at = starts.get(process_id)
        if not started_at:
            continue
        for host, port in data["endpoints"]:
            key = (process_id, started_at, port)
            previous = rows.get(key)
            if previous is None or host in ("*", "0.0.0.0", "::"):
                rows[key] = {
                    "pid": process_id,
                    "process": data["process"] or "Unknown process",
                    "cwd": cwd_by_pid.get(process_id, ""),
                    "host": host,
                    "port": port,
                    "startedAt": started_at,
                }
    return list(rows.values())


class LocalServerInventory:
    """Persist recent listeners and user-configured server profiles."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, ".local_servers.json")
        self.lock_path = self.path + ".lock"

    def snapshot(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with _inventory_lock(self.lock_path):
            return self._scan_and_store()

    def stop(self, server_id):
        if not isinstance(server_id, str) or not server_id:
            raise ValueError("Choose a server to stop.")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with _inventory_lock(self.lock_path):
            servers = self._scan_and_store()
            server = next((item for item in servers if item["id"] == server_id), None)
            if server is None or server["state"] != "running":
                raise ValueError("That server is no longer running. Refresh the list and try again.")
            pid = int(server["pid"])
            current_start = _process_start_times({pid}).get(pid)
            if not current_start or current_start != server["startedAt"]:
                raise ValueError("The process changed since this list was loaded. Refresh before stopping it.")
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                raise ValueError("That server has already stopped.")
            except PermissionError:
                raise ValueError("macOS denied permission to stop that process.")
            return {"ok": True, "server": server}

    def configure(self, server_id, command):
        command = command.strip() if isinstance(command, str) else ""
        if not command or len(command) > 4096 or "\0" in command:
            raise ValueError("Enter a launch command of 1–4096 characters.")
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        with _inventory_lock(self.lock_path):
            servers = self._scan_and_store()
            server = next((item for item in servers if item["id"] == server_id), None)
            if server is None:
                raise ValueError("That server is no longer in the recent list. Refresh and try again.")
            cwd = server.get("cwd")
            if not isinstance(cwd, str) or not os.path.isdir(cwd):
                raise ValueError("The server folder is no longer available. Configure it again from a running server.")
            try:
                port = int(server.get("port"))
            except (TypeError, ValueError):
                raise ValueError("The server port is invalid. Configure it again from a running server.")
            if not 1 <= port <= 65535:
                raise ValueError("The server port is invalid. Configure it again from a running server.")
            profile_id = _profile_id(cwd, port)
            payload = self._read_payload()
            profiles = {item["id"]: item for item in payload["profiles"] if isinstance(item, dict) and item.get("id")}
            profile = profiles.get(profile_id, {})
            profiles[profile_id] = {
                "id": profile_id,
                "cwd": os.path.realpath(os.path.expanduser(cwd)),
                "port": port,
                "command": command,
                "isPinned": bool(profile.get("isPinned")),
            }
            self._write({**payload, "profiles": list(profiles.values())})
        return {"ok": True, "profileId": profile_id}

    def set_pinned(self, server_id, pinned):
        if type(pinned) is not bool:
            raise ValueError("Choose whether to pin or unpin this server.")
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        with _inventory_lock(self.lock_path):
            servers = self._scan_and_store()
            server = next((item for item in servers if item["id"] == server_id), None)
            if server is None:
                raise ValueError("That server is no longer in the recent list. Refresh and try again.")
            profile_id = _profile_id(server["cwd"], server["port"])
            payload = self._read_payload()
            profiles = {item["id"]: item for item in payload["profiles"] if isinstance(item, dict) and item.get("id")}
            profile = profiles.get(profile_id, {
                "id": profile_id,
                "cwd": os.path.realpath(os.path.expanduser(server["cwd"])),
                "port": int(server["port"]),
                "command": "",
            })
            if pinned:
                profile["isPinned"] = True
                profiles[profile_id] = profile
            elif profile.get("command"):
                profile["isPinned"] = False
                profiles[profile_id] = profile
            else:
                profiles.pop(profile_id, None)
            self._write({**payload, "profiles": list(profiles.values())})
        return {"ok": True, "profileId": profile_id, "isPinned": pinned}

    def start(self, profile_id):
        if not isinstance(profile_id, str) or not re.fullmatch(r"[0-9a-f]{20}", profile_id):
            raise ValueError("Choose a valid configured server to start.")
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        with _profile_start_lock(f"{self.lock_path}.start.{profile_id}"):
            with _inventory_lock(self.lock_path):
                servers = self._scan_and_store()
                payload = self._read_payload()
                profile = next((item for item in payload["profiles"] if item.get("id") == profile_id), None)
                command = profile.get("command") if profile else None
                if not isinstance(command, str) or not command.strip() or "\0" in command or len(command) > 4096:
                    raise ValueError("Save a launch command for this server before starting it.")
                if any(item.get("profileId") == profile_id and item.get("state") == "running" for item in servers):
                    raise ValueError("That server is already running.")
                cwd = profile.get("cwd")
                if not isinstance(cwd, str) or not os.path.isdir(cwd):
                    raise ValueError("The saved server folder no longer exists. Configure the launch command again.")
                try:
                    port = int(profile.get("port"))
                except (TypeError, ValueError):
                    raise ValueError("The saved server port is invalid. Configure the launch command again.")
                if not 1 <= port <= 65535:
                    raise ValueError("The saved server port is invalid. Configure the launch command again.")
                if _profile_id(cwd, port) != profile_id:
                    raise ValueError("The saved server profile is invalid. Configure the launch command again.")
                if any(_uses_running_port(item, port) for item in servers):
                    raise ValueError(f"Port {port} is already used by another local server.")
                try:
                    process = subprocess.Popen(
                        ["/bin/zsh", "-lc", command],
                        cwd=cwd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        close_fds=True,
                    )
                except OSError as error:
                    raise ValueError(f"Could not launch the saved command: {error.strerror or error}.")

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                snapshot = self.snapshot()
                server = next((item for item in snapshot["servers"]
                               if item.get("profileId") == profile_id and item.get("state") == "running"), None)
                if server:
                    return {"ok": True, "server": server}
                exit_status = process.poll()
                if exit_status is not None:
                    raise ValueError(f"The launch command exited with status {exit_status} before port {port} opened.")
                time.sleep(0.4)
            raise ValueError(f"The launch command did not open port {port} within 15 seconds.")

    def restart(self, profile_id):
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("Choose a server to restart.")
        snapshot = self.snapshot()
        server = next((item for item in snapshot["servers"]
                       if item.get("profileId") == profile_id and item.get("state") == "running"), None)
        if server is None:
            raise ValueError("That server is no longer running. Refresh the list and try again.")
        self.stop(server["id"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            snapshot = self.snapshot()
            if not any(item.get("profileId") == profile_id and item.get("state") == "running"
                       for item in snapshot["servers"]):
                return self.start(profile_id)
            time.sleep(0.3)
        raise ValueError("The server did not stop in time, so it was not restarted.")

    def _scan_and_store(self):
        now = _now()
        stamp = _stamp(now)
        payload = self._read_payload()
        profiles = {
            item["id"]: item for item in payload["profiles"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        old = payload["servers"]
        by_id = {}
        for item in old:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            item = dict(item)
            started_at = item.get("startedAt")
            try:
                server_id = _server_id(item.get("pid"), started_at, item.get("port"))
            except (TypeError, ValueError):
                server_id = item["id"]
            item["id"] = server_id
            if isinstance(started_at, str):
                item["startedAt"] = started_at.strip()
            previous = by_id.get(server_id)
            if previous:
                first_seen = [value for value in (previous.get("firstSeen"), item.get("firstSeen")) if value]
                if item.get("lastSeen", "") > previous.get("lastSeen", ""):
                    by_id[server_id] = item
                if first_seen:
                    by_id[server_id]["firstSeen"] = min(first_seen)
            else:
                by_id[server_id] = item
        uid = os.getuid() if hasattr(os, "getuid") else getpass.getuser()
        live = [row for row in _listener_rows(uid) if _is_local_server(row)]
        seen = set()

        for row in live:
            server_id = _server_id(row["pid"], row["startedAt"], row["port"])
            seen.add(server_id)
            previous = by_id.get(server_id, {})
            by_id[server_id] = {
                "id": server_id,
                **row,
                "project": os.path.basename(row["cwd"].rstrip(os.sep)) if row["cwd"] else "",
                "state": "running",
                "firstSeen": previous.get("firstSeen", stamp),
                "lastSeen": stamp,
                "stoppedAt": None,
            }

        for server_id, item in by_id.items():
            if server_id not in seen and item.get("state") == "running":
                item["state"] = "stopped"
                item["stoppedAt"] = stamp

        for item in by_id.values():
            try:
                profile_id = _profile_id(item.get("cwd", ""), item.get("port"))
            except (TypeError, ValueError):
                profile_id = ""
            profile = profiles.get(profile_id, {})
            item["profileId"] = profile_id or None
            item["isConfigured"] = bool(profile.get("command"))
            item["isPinned"] = bool(profile.get("isPinned"))

        cutoff = now - timedelta(days=_HISTORY_DAYS)
        kept = []
        for item in by_id.values():
            last_seen = _parse_stamp(item.get("lastSeen"))
            if item.get("isPinned") or (last_seen and last_seen >= cutoff):
                kept.append(item)
        kept.sort(key=lambda item: (
            item.get("isPinned", False), item.get("state") == "running", item.get("lastSeen", "")
        ), reverse=True)
        kept = kept[:_MAX_SERVERS]
        payload = {"updatedAt": stamp, "servers": kept, "profiles": list(profiles.values())}
        self._write(payload)
        return {"updatedAt": stamp, "servers": [item for item in kept if _is_local_server(item)]}

    def _read(self):
        return self._read_payload()["servers"]

    def _read_payload(self):
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            servers = payload.get("servers", [])
            profiles = payload.get("profiles", [])
            return {
                "updatedAt": payload.get("updatedAt", ""),
                "servers": servers if isinstance(servers, list) else [],
                "profiles": [item for item in profiles if isinstance(item, dict) and isinstance(item.get("id"), str)]
                    if isinstance(profiles, list) else [],
            }
        except (OSError, ValueError, TypeError):
            return {"updatedAt": "", "servers": [], "profiles": []}

    def _write(self, payload):
        directory = os.path.dirname(self.path)
        fd, temporary = tempfile.mkstemp(prefix=".local_servers.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
