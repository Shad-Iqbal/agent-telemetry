# Account information and subscription limits

Research and implementation notes, verified 2026-10-12. The feature appears in the
web Overview, including the macOS embedded dashboard. Native tray/menu summaries
continue to show today's usage; this change does not add quota meters to those panels.

## Sources and evidence

| Source | Reliable fields | Limits of the evidence |
| --- | --- | --- |
| Codex rollout `session_meta` | `creator_account_id`, `creator_user_id` | Thread creator only. A resumed thread, fork or running process can use another account. Not per-request billing attribution. |
| Codex `event_msg/token_count.rate_limits` | `used_percent`, `window_minutes`, `resets_at`, optional bucket and plan | Account-wide observation at the event timestamp. The snapshot has no billing account ID. Recent local logs contained 300-minute and 10080-minute windows. |
| Codex app-server | `account/read` account type/email/plan; `account/rateLimits/read` bucket windows | Explicit one-time lookup via the CLI on the dashboard's PATH and its `CODEX_HOME`. Other processes/app profiles may use different auth. Missing fields remain unknown. |
| Claude transcript top-level `accountUuid` | Account IDs observed in records | Optional and historically incomplete. Does not establish auth, plan or per-request payer. Recent inspected transcripts contained no continuous percentage snapshots. |
| Claude `auth status` | Auth method, provider, optional email/org/plan | Explicit one-time CLI lookup, not retrospective session attribution. No quota percentages. CLI versions/provider setups may omit fields. |
| Claude status-line stdin | `rate_limits.five_hour` / `seven_day`: `used_percentage`, `resets_at` | Optional subscriber fields after an API response. No account identity; cannot bind a capture to the current sign-in. Gateway spend limits are a separate concept and are excluded. |

Primary references:

- [OpenAI Codex app-server auth endpoints](https://learn.chatgpt.com/docs/app-server#auth-endpoints)
- [Claude CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude status-line reference](https://code.claude.com/docs/en/statusline)
- [Claude monitoring identity attributes](https://code.claude.com/docs/en/monitoring-usage)

The supplied Codex screenshot showed ChatGPT Plus with 89% remaining in both windows.
It is a visual reference, not a live data source. Tests use synthetic 11%-used snapshots
to reproduce those bars; no real account, transcript or screenshot is committed.

## Behavior and privacy

The default view reads only local, allowlisted observations. It does not read/decode
credential contents or scrape account websites. GET `/api/accounts` never runs a CLI
or contacts a provider. Each **Refresh account & limits** / **Refresh account** action
shows the local consent dialog and makes one guarded JSON POST with `confirmed:true`.
There is no background network polling or permanent opt-in. CLI reads never start,
resume or run a model turn, login, logout, buy credits, or redeem quota resets.

Codex reads account before and after the quota request on one app-server connection.
Account/file changes during the lookup discard the result. Later credential-file
signature changes hide its previous account identity and quotas until another lookup.
CLI environment overrides are checked only for the dashboard process. External host
tokens, keychains and environment changes in other already-running apps cannot be
observed reliably, so this feature cannot promise their effective billing identity.

Snapshots are never summed across sessions, buckets, profiles or devices, and never
inferred from token counts, context-window utilization or estimated API cost. Local
log observations and Claude captures are explicitly unbound to current sign-in.
Quota cards are independent of usage date/model/project filters; selecting only a
remote device shows a source-device notice. Private session metadata is absent for
peer sessions and excluded by the device export allowlist.

Five minutes is AgentTelemetry's freshness policy, not a provider guarantee. Every
snapshot shows its observation time and reset time. Older/future timestamps, failed
reads, missing reset times and passed resets are stale. A reset passing does not make
the meter 100% remaining: the last percentage is kept as a historical observation.
Absent or malformed fields show unavailable rather than zero usage. Account lookup
failure retains last successful values only while the local credential signature
matches, marks them stale, and allows a retry.
The web view reconciles a failed lookup with an offline local read. If that read
also fails, previous identities and live limits stay hidden until verified; retry
controls remain available. Windows-style log paths retain their profile grouping
when a copied ledger is read on macOS or Linux.

Credit balances, model-specific Claude weekly windows, exact remaining token/message
counts, plan pricing and historical per-request account attribution are not supported.
Subscription percentages do not establish how many requests remain or subscription
spend. Existing costs remain estimates at API list prices.

## Optional Claude capture

Claude does not write its documented status-line percentage payload into every
transcript. `accounts.py --capture-claude` accepts that JSON on stdin, stores only the
two subscriber windows in `AgentTelemetryNative/claude-quota-snapshot.json`, and emits
a short quota status line. The file is outside the durable ledger, so it does not
interfere with native ledger import. Missing windows replace the previous capture.
It stores no session paths, prompts, identity, credentials or gateway spend data.

To use it as your status line, **manually** set the command in your Claude user settings
to your Python executable followed by the absolute path to `accounts.py` and
`--capture-claude`. Resolve those paths from your own installation. For example, on
a checkout where you already invoke Python successfully:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"/absolute/path/to/agent-telemetry/accounts.py\" --capture-claude"
  }
}
```

This example is a replacement status line. If you have an existing status-line script,
preserve it: pass a copy of its original JSON stdin to the capture command, discard
the capture command's stdout, and keep your existing display output. AgentTelemetry
never edits Claude settings or installs a wrapper automatically. Restart/reconfigure
Claude using its documented workflow and wait for its next status-line update.

The capture is shared by local sessions; the latest completed capture wins, including
a payload with no quota fields. Its observation time is when the capture ran, not a
provider sample timestamp (the payload does not expose one). Idle sessions can emit
cached values. Captures therefore remain explicitly reported observations and carry
no identity even after a separate auth lookup. Pro/Max availability follows Claude's
documented payload; unsupported/API-key sessions show unavailable.

## Durable ledger and rollout

Cache version 57 adds optional private `account_metadata` and a backfill marker.
Versions 53–56 retain every ledger entry. Available Claude/Codex logs missing the
marker reparse transactionally; failure leaves the old entry/signature intact and
retries. Archived entries remain unchanged, with missing metadata shown as unknown.
Peers 52–56 remain readable. No rebuild is needed or performed. The account endpoint
is separate from `/api/data` and `/api/summary`; health remains free of identity and
analytics. Live account results are memory-only and disappear on backend restart.

Windows/macOS package allowlists include the new stdlib module without changing
published tags, dispatching builds, installing an update or publishing a release.
