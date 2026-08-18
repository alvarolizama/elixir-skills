# Confirming a flake before blaming your change (2026-08-05)

When `mix precommit` (or the full suite) goes red on a test UNRELATED to your
diff, the cheapest honest check is the isolation run:

1. Run the failing test FILE alone, twice: `mix test test/.../file.exs`
   - Green both times = shared-DB/ordering flake, not a regression.
2. Re-run the full suite once. Green = proceed with the commit; report the
   flake to the user in the summary.
3. Only block the commit on a failure that REPRODUCES in isolation.

## Worked instance — my_app `SearchControllerTest` (async: false)

`test "GET /api/search/semantic returns semantic search results"` uses a
`Req.Test.stub(my_app.Inference.Client, ...)` and creates a page with a
`Pgvector` embedding. Under full-suite load it intermittently fails:

- `assert length(data) == 1` → `left: 0`
- precommit run also showed `** (ArgumentError) construction of binary failed:
  segment 1 of type 'binary': expected a binary but got: nil`

Always passes solo (verified 2×) and the full suite went back to 519/519 on
re-run. Root cause NOT diagnosed — treat as a known flake; do NOT weaken its
assertions to hide it, and do NOT block unrelated commits on it.
