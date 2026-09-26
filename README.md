# AgentTelemetry

**Live, local telemetry for your AI coding agents.** AgentTelemetry reads the interaction
logs your tools already write to your own machine and serves a clean, interactive
dashboard — estimated spend, tokens, active time, cache efficiency, an **Anthropic vs OpenAI
vs Google** provider comparison, an activity calendar, and breakdowns by **model, provider,
day, hour, weekday, tool, IDE, project and session** — plus how much **disk** all these logs
eat, and suggestions for spending less, drawn from your own numbers.

**Your data never leaves your machine.** No account, no API key, no telemetry, no
dependencies — just Python's standard library and a vendored copy of Chart.js.

Covers **Claude Code · Claude Desktop · Codex · GitHub Copilot · Cursor · opencode · Hermes Agent**.

---

## Quick start

```bash
git clone https://github.com/uttamdeb/coding-agent-usage.git
cd coding-agent-usage
python3 dashboard.py
```

Then open **http://127.0.0.1:7878**. That's it — no `pip install`, no setup.

> First run parses your local logs (can take ~30–60s if you have large Codex logs), writes
> a cache, and is instant thereafter. The page auto-refreshes every ~15s, so a session
> you're running *right now* shows up within seconds.

Options: `python3 dashboard.py --port 9000` · `--rebuild` (ignore cache, full re-parse) ·
`--interval 20` (background refresh seconds). Or `./run.sh [flags]`.

**Requirements:** Python 3.8+ on **macOS, Linux or Windows**. On Windows run
`python dashboard.py` (or `run.cmd`); on macOS/Linux `python3 dashboard.py` (or `./run.sh`).

It works on anyone's machine because **nothing is hardcoded** — every location is derived at
runtime from your own `$HOME` / `%APPDATA%` / `%LOCALAPPDATA%` / `$XDG_*`, the numbers are
read live from your own logs on every refresh, and the disk figures come from your own drive.
Two people running this see two completely different dashboards.

---

## Everyone sees *their own* usage

This is the important part if you're sharing it: the dashboard has **no bundled data**.
On each machine it scans that user's own logs (`~/.claude`, `~/.codex`,
`~/Library/Application Support/…`, `~/.local/share/opencode`, `~/.hermes`, …) and builds a **fresh**
`.usage_cache.json` locally. That cache is **gitignored and never committed**, so a clone
starts empty and shows only the cloning user's numbers. (If you ever *copy the folder*
instead of cloning, delete `.usage_cache.json` first — that file is your personal data.)

---

## Data sources

| Tool | Where it reads | Tokens |
|---|---|---|
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | exact (in/out/cache read+write, 5m/1h tiers) |
| **Claude Desktop** (agent mode) | `Claude/local-agent-mode-sessions/**` under App Support / `%APPDATA%` / `~/.config` | exact |
| **Codex** | `~/.codex/sessions/**`, `~/.codex/archived_sessions/**` | exact (in/cached/out/reasoning); subagents are identified and labelled |
| **GitHub Copilot** | VS Code / Insiders / Cursor `workspaceStorage/*/chatSessions/*.{json,jsonl}` | exact where Copilot recorded them (`promptTokens`/`completionTokens` on finished requests in current builds); estimated from message text for older chats · premium-request multiplier read separately |
| **Cursor** (native AI) | `Cursor/User/globalStorage/state.vscdb` under App Support / `%APPDATA%` / `~/.config` | partial — model, mode, timestamps, tool calls and AI-line stats are exact; tokens are on only ~2% of messages |
| **opencode** | `~/.local/share/opencode/opencode.db`, `%LOCALAPPDATA%\opencode\opencode.db`, `~/.opencode/opencode.db` (or `$OPENCODE_DATA_DIR`) | exact (in/out/reasoning/cache); cost is read from opencode's own per-message value |
| **Hermes Agent** | `~/.hermes/state.db` (or `$HERMES_HOME`, `%LOCALAPPDATA%\hermes`) | exact (in/out/cache/reasoning, per model) |

A tool you don't use simply contributes nothing. **Attribution is by tool, not by model** —
a Claude or GPT model used *inside* Copilot/Cursor/opencode/Hermes counts under that tool, and the
Models table lists each `model × tool` row separately.

---

## What you get

Eight views in a left-hand sidebar, light + dark theme, everything date-filterable, and the
**name of this machine** at the top — so a screenshot always says which computer it came from.

One control row sits above every view: the **period** (Today · 7D · 30D · 90D · All, plus
*More* for this week / month / quarter / year, last month and a custom range), the **measure**
(**Cost · Tokens · Time** — every chart and ranking switches together), and a single
**Filters** panel (tool, provider, model, project, IDE / surface, and *exact tokens only*).
Active filters show as removable chips. Every figure is compared with the equal-length
period just before it, and every chart has a **table view** (the grid icon) so nothing is
readable only by hovering.

**Overview** — one hero number with its change vs the previous period · per-day chart
stacked by tool · tiles for spend, tokens, active time, prompts, replies, sessions and cache
hit rate, each with a sparkline · spend by tool · top models · top projects · highlights ·
**hour × weekday heatmap** · token mix per tool · 12-month activity calendar (click a day).

**Cost** — total with per-active-day, 30-day run rate, per session and per prompt ·
cumulative spend by tool against the previous period · **cache hit rate and what caching
saved you** · spend by model, by project and by **token type** (what cache reads vs writes vs
output actually cost you) · effective rate by model, as *all tokens* or *per output* (the one
that's comparable across providers) · daily spend.

**Models** — provider cards (who made the model, independent of the tool that ran it) ·
sortable `model × tool` table with a ⚠ on any model missing a price · model timeline ·
provider share over time · **provider × tool matrix**.

**Tools & agents** — active time, tool calls per prompt, context amplification, subagent
share, MCP and web calls, Copilot premium requests, Cursor's AI lines kept · top tool calls
· calls by category · **where you work** (IDE × tool) · MCP servers · **Skills** · the full
tool list.

**Projects** — ranked by the chosen measure, concentration stats, and a searchable table
where clicking a row opens that project's sessions.

**Sessions** — real session titles, tool, project, model, tokens, cost, prompts, replies,
tool calls, active time, cache % — search, sort, and click any row for a detail panel.

**Optimize** — suggestions derived from your own logs, ranked by what they'd save: sessions
re-reading a very large context, thinking share, tool-heavy sessions that never delegated,
cache written but never read, a costly model doing light work, what each **Skill** costs,
MCP servers you connected but never call, Codex reasoning effort. Nothing is shown unless
your data supports it, and because the estimates overlap they are never summed.

**Storage** — see below.

**Keyboard** — `1`/`7`/`3`/`9`/`a` ranges, `m` month-to-date, `/` search, `t` theme, `r` refresh.

---

## Storage — what these logs cost you in disk

The tools you use write a *lot* to disk, and nothing else tells you how much. The **Storage**
tab shows total footprint and per-tool bytes, a free-space gauge that warns when the drive is
nearly full, storage accumulation over time, the largest individual log files, **bytes per 1M
tokens** (which tool stores its history most expensively), AI data on disk AgentTelemetry does
*not* analyse, and copy-paste cleanup commands **generated for your own paths and your own
shell** (`find` on macOS/Linux, PowerShell on Windows). AgentTelemetry never deletes anything
itself.

Deleting old logs does **not** shrink your analytics — AgentTelemetry keeps every session it has
already parsed, so the cleanup is safe.

---

## Cost notes (read this)

Costs are **estimates** computed as `tokens × price` — the tools store token counts, **not
dollars**, so cost is always derived. Rates live in `parser.py → PRICING` as
`(input, output, cache_write_5m, cache_write_1h, cache_read)` per 1M tokens; edit freely
(recomputed on each request, no re-parse needed).

- **Anthropic** rates are current list prices (Opus 5.5 $4/$20, Opus 5 & 4.x $5/$25, Sonnet 5
  $2/$10, Sonnet 4.x $3/$15, Haiku $1/$5; cache write 1.25×/2× input for 5-min/1-hour, cache
  read 0.1× — 0.05× on Opus 5.5). **OpenAI** GPT-5.4/5.5/5.6/6 are verified from OpenAI docs;
  older/other models are estimates.
- **Price changes are date-aware.** When a vendor cuts a price (OpenAI's GPT-5.6 cuts of
  2026-07-30 and 2026-08-21), usage from before the change keeps the rate it had then —
  see `parser.py → PRICE_HISTORY`.
- **These are API-equivalent values.** If you're on a subscription (Claude Max/Pro, Codex,
  Copilot), you don't pay per token — the $ is "what this would cost at API rates."
- **Copilot / Cursor** don't log real token counts, so their tokens (and thus $) are rough.
  Copilot's honest metric is **request count** and its **premium-request** total (both shown);
  Cursor's is **messages, tool calls and AI lines kept** (also shown).
- A model with no price row reads as **$0** — add it to `PRICING` (see below).

## Note on log retention

Some tools delete old logs. **Claude Code** prunes transcripts after `cleanupPeriodDays`
(default **30**); **Codex** keeps everything. The dashboard also keeps parsed sessions in
its cache even after a tool deletes the on-disk log, so totals don't silently shrink once seen.

You can change Claude Code's retention window from the dashboard itself — the **⚙** button
in the header edits `cleanupPeriodDays` in your own `~/.claude/settings.json` (leave it blank
to fall back to the tool's default). The write is atomic and keeps a `.bak`; every other
setting in the file is preserved untouched. It's the only file outside its own cache that the
dashboard ever writes.

---

## Extending it

- **Add a model's price / fix an unknown model:** edit `PRICING` (and, if needed, the
  model-name normalizer) in `parser.py`. Verify rates against the vendor's docs.
- **Add a new tool:** add its paths + a `parse_*` function in `parser.py`, wire `discover()`
  and `update_file()`, then add it to `SRC`/`ORDER` in `static/core.js` and give it a
  `--t-<source>` colour in `static/app.css`. The tool colours are a colour-blind-validated
  palette whose *order* is the safety mechanism — see AGENTS.md before changing them.

See **[AGENTS.md](AGENTS.md)** for a concise, agent-oriented guide (any coding agent can run
and extend this from that file).

## Files

`dashboard.py` (server + cache + cost + `/api/storage`) · `parser.py` (log parsers + pricing) ·
`index.html` (shell) · `static/app.css` · `static/core.js` · `static/charts.js` ·
`static/views.js` · `chart.umd.min.js` (vendored Chart.js) · `AGENTS.md` · `run.sh`.

## Install it as an app (optional)

The dashboard can run as a standalone window in your Dock or taskbar. It's **off by
default** — open the **⚙** menu and turn on *Install as an app*, then use your browser's
Install / Add to Dock. That registers a service worker so the shell still opens when
`dashboard.py` isn't running; your usage data is never cached, `/api/` always hits the live
server. Turning it off again unregisters the worker and clears its cache.

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)** — it covers the setup, the hard rules
(stdlib only, nothing hardcoded, never commit your cache), how to add a tool source or
a model price, and how to test a change. **[AGENTS.md](AGENTS.md)** is the architecture
guide. Please read the note on setting your git email before your first commit.

Found a security problem? See **[SECURITY.md](SECURITY.md)** — don't open a public issue.

## License

MIT — see [LICENSE](LICENSE).
