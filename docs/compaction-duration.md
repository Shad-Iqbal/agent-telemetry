# Codex compaction duration recovery

Investigation on 2026-10-12 found that commit `c6b5961` correctly counts Codex's
durable checkpoints, but its blanket statement that duration is never recorded is
too broad. A `compacted` checkpoint has no duration field; some companion top-level
`event_msg/item_completed` records for `ContextCompaction` contain
`started_at_ms` and `completed_at_ms`.

The implementation now reads those explicit timestamps. It does not estimate time
from adjacent log lines, a whole turn, token usage, or copied replacement history.
Matching requires:

1. The checkpoint's `compaction_response_id` matches an observed **top-level**
   `token_usage_record.response_id` with a recorded turn and thread ID.
2. The completion has the same turn/thread IDs and valid integer start/end epoch
   milliseconds. A known session ID must also match that thread.
3. Exactly one durable checkpoint lies within that reported operation interval,
   and exactly one completion covers that checkpoint. Missing IDs, conflicting
   replays and overlapping candidates leave duration unknown.

Completion records only enrich the original event; they create no event, model call,
tokens, cost, active time, hourly record or session-boundary changes. A bounded private
parser-state map supports incremental parsing and restarts. The uniqueness check
includes all durable checkpoints, including ones without correlation metadata.

The existing event schema already permits numeric `duration_ms` (used by Claude).
No aggregate or payload shape changes, so no cache-version bump is necessary. A
private parser-state version triggers one transactional reparse of available Codex
logs, even on an unchanged file signature. Failed reparses retain the previous ledger
and retry. Archived logs stay unchanged. Never run `--rebuild` for this backfill.

Read-only comparison against the unchanged main parser on the three inspected
rollouts recovered 12/18, 2/3 and 24/24 durations. All usage dimensions and event counts
were identical. One event had a recorded 163391 ms duration and now renders as 163s.
No transcripts, account metadata or real usage records are committed as fixtures.

Manual/auto trigger and before/after context sizes remain unknown for these Codex
records: they do not contain those fields. The example with manual/auto labels and
context sizes matches this dashboard's Claude-specific renderer, which reads
`compactMetadata.trigger`, `preTokens`, `postTokens` and `durationMs`. The Mac transcript
itself was not available for inspection; OS alone does not determine these fields.

The [official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server)
describes `contextCompaction` items and their completion lifecycle. The extra epoch
timing fields above were verified in local rollout records; they are optional and
are not guaranteed by that documentation.
