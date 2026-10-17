# Local server controls

The **Local servers** dashboard view and macOS menu can list TCP listeners owned by
the current user, save a launch command, pin a server, and start, stop or restart it.
These controls currently require macOS and a ready AgentTelemetry backend. Windows
and Linux display an unsupported state; their telemetry dashboards continue to work.
An older backend must be upgraded before the native menu can manage servers.

## What is observed

Discovery uses the local `lsof` and `ps` utilities. A row identifies a process by its
PID, recorded start time and listening port. The working directory supplies the
project name. Listeners with an unavailable working directory, system directories,
and AgentTelemetry's own backend are excluded. This is a filtered listener inventory,
not a complete inventory of applications or websites. It does not inspect process
arguments, credentials or other processes' environment variables.

TCP does not identify HTTP versus HTTPS or another protocol. A detected port is not
proof that a web page is ready. Discovery failures remain errors, with the previous
successful list marked stale, rather than being interpreted as every server stopping.

## Saved commands and process actions

Configure stores the command typed by the user with the discovered working directory
and expected port. Saving and pinning never run a command. Start and Restart require
explicit confirmation and execute the saved command through `/bin/zsh -lc` in that
directory. Shell startup files may run as part of that execution. The command inherits
the backend's normal environment, excluding AgentTelemetry's backend control token;
it does not recover the original server's environment or terminal setup.
The inventory scan makes no network requests. A command you explicitly run can access
files and the network with your account's permissions.

Stop sends SIGTERM to the selected listener process after checking its identity
again. Other ports owned by that process can stop too. Restart validates the saved
profile, stops the confirmed process, waits, then launches the saved command. A
changed process is refused. Commands that daemonize or deliberately leave the launch
process group cannot always be attributed safely and may remain unverified.

Startup must be observed at the expected port before it is reported successful. A
timeout or launch error is shown without silently retrying. AgentTelemetry is not a
process supervisor: it does not capture server output, force-kill on timeout, restore
terminal sessions, or automatically restart a server after it exits. Inspect the
server before retrying a timed-out command, since it may still be starting.

## Storage and privacy

Recent observations, pins and commands are private to this installation, in
`.local_servers.json` beside the backend's selected data directory. They are not part
of the telemetry ledger, health, summary or device-sharing payloads. Commands can
contain secrets; use environment references rather than saving credentials in them.
The file is excluded from Git and installation payloads. Unreadable or corrupt
inventory files are preserved and reported, not silently replaced with empty data.

The API requires a loopback client. Writes additionally require the dashboard's
same-origin JSON guard. Start, Stop and Restart require `confirmed:true`; Restart
also identifies the exact server row that was confirmed. Inventory updates use both
an in-process lock and a file lock so separate requests and backend processes do not
overwrite each other's changes. No telemetry cache migration or rebuild is required.

Implementation references: [Apple's file-lock semantics](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fcntl.2.html)
and Python's [subprocess environment and session controls](https://docs.python.org/3/library/subprocess.html#popen-constructor).
