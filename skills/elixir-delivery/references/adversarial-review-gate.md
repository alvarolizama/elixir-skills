# Adversarial Review Gate — pre-commit review of a delivery wave

Symptom: the author of a wave self-approves it, and the bugs the suite
masked (cross-workspace leaks, silent constraint failures) ship. Mechanism:
authorship biases review; the gate is a review pass with the diff as the
only input — who writes does not self-approve.

> Scope: this is the delivery-side pre-commit dispatch gate. The general
> reviewer posture it implements (who-self-approves, blast-radius
> enumeration, read-before-conclude) lives in
> `skills/elixir-review/references/adversarial-review-protocol.md`.

## The gate

Before committing, dispatch a review delegation whose only input is the
diff. Blocking criteria for the reviewer:

- Secrets or credentials in the diff (including hardcoded fallback values).
- Debug leftovers (IO.inspect, console.log, commented-out code).
- Migration / structure.sql drift.
- Missing module references (calls to modules that don't exist, broken
  aliases).
- (Minimum own checklist fallback: auth row-level scoping, deterministic
  pagination order, N+1 queries, assigns leaks, contract with the rest of
  the codebase.)

Only APPROVE → commit → push.

## Death protocol (503 / max_iterations)

A reviewer that died is NOT an approval:

1. Re-dispatch ONCE with a narrow goal (3–4 concrete points, shorter brief).
   Two adjustments that turn dead reviews into delivered ones: state the
   required output as an explicit "your final answer must be EXCLUSIVELY a
   JSON object with keys ..., no text outside the JSON" instruction instead
   of a strict output_schema (strict schema + flaky provider = HTTP 500
   retries and death), and keep the brief short.
2. If the re-dispatch also dies: do the adversarial pass YOURSELF on the
   diff, plus one ad-hoc test per suspicion, and record explicitly
   "review delegated: not completed (503)".
3. Before re-launching, harvest the live transcript's `think` lines —
   half-written findings may already be there (a real PubSub topic mismatch
   was known this way before any verdict arrived).

## Verdict recovery — the transcript lies

- The live transcript log truncates lines (~300 chars); its tail is NOT the
  full verdict, and the delegation manifest does not store the summary.
- The full text arrives with the async delegation batch or in
  `cache/delegation/subagent-summary-<n>-*.txt` — that file exists from the
  moment the child finishes; read it without waiting for the notification.
- A real finding (a ghost cross-goal edge drawn to {0,0}) was invisible in
  the truncated tail.
- **Late notification = mandatory re-triage.** The batch can arrive AFTER
  you closed triage from the truncated transcript — and it carries the full
  report (case: triage closed with "1 blocker refuted + 1 major fixed";
  the late report revealed 3 more unaddressed majors). Never answer
  "already processed" without re-reading the summary file.

## Processing findings on the uncommitted wave

- Bugs introduced by the wave itself → fixes go in the SAME wave commit (the
  wave is the atomic unit). After each fix re-run
  `mix compile --warnings-as-errors` and the full gate set — the previous
  green run has expired.
- **Validate and EXTEND before fixing:** reproduce the bug yourself
  (`mix run --no-start` with a real struct; plain `mix run` dies
  `:eaddrinuse` with the dev server up) and grep the CONSUMERS of the buggy
  function before choosing the fix. Real case: `dependency_edges/1` filtered
  only by source (ghost edges in the DAG), but `dependency_states/1`
  consumed the same edges for readiness — the naive fix would have marked a
  blocked task ready. Correct fix: TWO queries with different semantics,
  cross-documented in their `@doc`s.
- Recurring code pits surfaced by reviews: every `case` on
  `Repo.update/insert` inside a transaction must handle
  `{:error, %Ecto.Changeset{}}` (declared constraints produce it; a case
  expecting only typed atoms dies with CaseClauseError). Moving a
  `handle_event` body into a `defp` (e.g. to add a guard) — place the
  `defp` in the private section, leaving it mid-clauses splits
  `handle_event/3` and `--warnings-as-errors` rejects it. Verify real
  reachability before adding UI for an error path (an impossible `:cycle`
  during create needs no speculative message — refute and document).
- `Enum.join` over a list mixing binaries and sublists CONCATENATES without
  separators (`## Claims- **P1**` glued together) — `List.flatten` before
  the join, and assert line borders (`"\n## Claims\n"`,
  `refute "Claims- **"`) because substring asserts pass either way.

## LiveView list/incremental-load checklist (always in the pass)

- "Load more" that refetches from 0 with `limit: (page+1)*size` → O(n²);
  must be `offset: page*size, limit: size+1`, concatenating in the socket.
- `order_by` without a deterministic tiebreaker under offset/limit → rows
  cross page boundaries; add `desc: :id`.
- Double mutation: `handle_event` writes AND a PubSub broadcast triggers
  `handle_info` that re-reads — decide: intentional-and-cheap (comment it)
  or dedupe.
- `Process.sleep` in PubSub tests → fragile; prefer retry/monitor.
- `rescue _ -> 0/[]` in UI code silencing real DB errors → acceptable only
  if degradation is the right choice; comment it.

## Cross-workspace leak pattern (found by review, missed by ConnCase)

A delete/feedback endpoint validated the write-access plug against
`params["workspace"]` but mutated any row by id (`Repo.get` without a
workspace filter). Fix pattern: a scoped getter returning nil for missing OR
foreign rows (callers must not distinguish — no existence oracle), 404, plus
regression tests asserting the foreign row is UNTOUCHED (fields unchanged),
not just that the 404 came back.

## Post-push findings

The reviewer may deliver after you committed:

- **Real warn, self-correcting** (a <100ms window that heals): document as
  known debt in a code comment via a separate `docs:` commit — never mix a
  new behavior change without its own validation into an already-pushed
  commit.
- **Misleading comment** (asserts something false about the mechanism):
  correct it in the same docs commit.
- **Style nit / pre-existing debt** (yet another modal missing the same
  guard, vulnerable before this wave): report, don't touch out of scope.

The review hunted blockers; no blockers → APPROVE stands and the warn
becomes documentation, not an off-schedule fix.

## Verification

- Review verdict read from the FULL summary file (not the transcript tail),
  or the death protocol executed and recorded.
- Every blocker fixed with a self-reproduction + consumer-grep note; gates
  re-run after the last fix.
- Post-push findings dispositioned: docs commit / report-only, each with
  evidence.
