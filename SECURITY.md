# Security Policy

## What this project is, security-wise

AgentTelemetry reads the interaction logs your AI coding tools already write to
your own machine and serves them back to you as a local web page. That makes it a
**local web server with access to some of the most sensitive text on your disk** —
your prompts, session titles, project names and file paths.

Two properties are load-bearing, and any change that weakens them is a
vulnerability:

1. **Nothing leaves the machine unless you ask.** No telemetry, no analytics, no API
   keys. Chart.js is vendored precisely so the page never fetches from a CDN. The only
   network use is opt-in: the **Check for updates** button (a `git fetch`, on click),
   and **Your devices**, which you turn on in Settings (below).
2. **It binds to `127.0.0.1` by default** and has **no authentication whatsoever**.
   It trusts anything that can reach its port.

## Supported versions

This is a single-branch project. Fixes land on `main`; please report against the
latest commit there.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private vulnerability reporting:
**Security → Advisories → Report a vulnerability** on this repository. That opens a
private thread with the maintainer.

Please include what an attacker can reach, what they gain, and a reproduction if you
have one. This is a personal project maintained by one person — expect a best-effort
response, not an SLA.

## Things you should know as a user

**`.usage_cache.json` is your personal data.** It holds parsed tokens, costs,
project names, session titles and timestamps. It is gitignored and must never be
committed. If you *copy* this folder rather than cloning it, delete that file first —
otherwise you are handing someone your usage history.

**Do not expose the port.** `--host 0.0.0.0` puts an unauthenticated dashboard of
your prompt history on the network, and it is not built to survive that. Keep it on
loopback. The same applies to port-forwarding it, tunnelling it, or running it on a
shared machine where other users can reach loopback.

**Sharing with your devices exposes one read-only route, and only while it's on.**
Settings → Your devices → *Share this device* opens a second listener on port 7879 on
your network. It answers only `GET /api/peer/export`, and only to a request carrying the
pairing code (compared in constant time, and a wrong guess waits a second). It returns your
usage aggregates: session titles, project and branch names, log file paths, models,
tokens, costs and times. Never full prompts, replies or file contents. The dashboard and
its write endpoints stay on `127.0.0.1`. The connection is **not encrypted**, so anyone
who can watch the network sees what is sent. Share only on a network you trust, and use
*New code* if the code leaks. Pairing codes and the copies pulled from your other
devices sit in `.peers.json` and `.peers/` (0600, gitignored).

**`~/.claude/settings.json` is the only file outside its own cache that this app
writes.** The ⚙ settings panel edits Claude Code's `cleanupPeriodDays` there. The
write is read-modify-write (other keys are preserved), atomic via `os.replace`, and
leaves a `.bak`. Writes are rejected cross-site — see below.

**Log retention is a destructive setting.** `cleanupPeriodDays` controls when Claude
Code deletes your transcripts. Anything that can change it can cause data loss, which
is why the write endpoint is guarded.

## Threat model and existing mitigations

| Concern | Mitigation |
|---|---|
| A website you visit silently POSTing to the local API (CSRF) | `POST /api/settings` requires `Content-Type: application/json`, which forces a CORS preflight that is deliberately never answered, and rejects any non-same-origin `Origin` / `Sec-Fetch-Site`. A cross-site write returns `403`. |
| Someone on your network reading a shared device's usage | Sharing is off by default and asks before it starts. Only `/api/peer/export` is served on the network port, behind a ~59-bit pairing code, with a 1s delay per wrong guess. Nothing on that port writes anything. |
| A connected device sending malformed data | The export is size-capped (512 MB decompressed), must identify as AgentTelemetry at the same `CACHE_VERSION`, and entries without the expected shape are dropped. Log-derived strings are escaped as for local logs. |
| Reading arbitrary files through `/static/` | Path is normalised and must stay under `static/`; anything else is `404`. |
| Malicious content inside a parsed log rendering as HTML | All log-derived strings are escaped before insertion into the DOM. Log files are attacker-influenced if you ever paste untrusted text into a coding tool — treat them as untrusted input. |
| SQL injection via Cursor's / opencode's SQLite stores | Queries are static; no value from a log is ever interpolated into SQL. Databases are opened read-only (`mode=ro`). |
| Supply chain | Standard library only. There is nothing to `pip install`, and no dependency can be substituted at install time. |

## Out of scope

- Anyone with local access to your user account. They can read the logs directly;
  this tool grants no extra reach.
- The accuracy of cost estimates. Wrong numbers are bugs, not vulnerabilities —
  please open a normal issue.
- Denial of service against your own loopback server.
