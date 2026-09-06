# API e2e Smoke — real-server curl cycle for REST waves

Symptom: a wave adds REST endpoints; ConnCase passes; the first real client
fails. Mechanism: `ConnCase` mocks (e.g. `Req.Test`) prove the controller
contract, not the HTTP surface — router plugs, real auth pipelines, and JSON
encoding of exotic column types (pgvector) only exist on a booted server.

## The cycle

1. **Pick an alternate port and check it's free**, then boot a real server
   in the background, full output to a file:

   ```bash
   PORT=4001 mix phx.server > /tmp/phx_e2e.log 2>&1 &
   curl -s -o /dev/null -w "%{http_code}" http://localhost:4001/health || true
   ```

2. **curl cycle with a real bearer token**, covering at least:
   create → duplicate → search → unauthorized (401) → cross-workspace (404).

   ```bash
   BASE=http://localhost:4001/api
   AUTH="Authorization: Bearer $TOKEN"

   curl -s -X POST $BASE/items -H "$AUTH" -H "content-type: application/json" \
     -d '{"name":"e2e-row"}' -o /tmp/create.json -w "create=%{http_code}\n"
   curl -s -X POST $BASE/items -H "$AUTH" -H "content-type: application/json" \
     -d '{"name":"e2e-row"}' -o /tmp/dup.json -w "duplicate=%{http_code}\n"
   curl -s "$BASE/items/search?q=e2e" -H "$AUTH" -o /tmp/search.json -w "search=%{http_code}\n"
   curl -s "$BASE/items" -o /dev/null -w "noauth=%{http_code}\n"                 # expect 401
   curl -s -X DELETE "$BASE/items/$FOREIGN_ID" -H "$AUTH" \
     -o /dev/null -w "cross=%{http_code}\n"                                      # expect 404
   ```

   To inspect JSON, save the response to a file and run
   `python3 -m json.tool /tmp/create.json` — piping curl straight into an
   interpreter trips security scanners (the `curl | python3` upload shape).

3. **Kill the server, then clean e2e rows from the dev DB** — they leak into
   the user's real workspace otherwise:

   ```bash
   kill %1
   psql my_app_dev -c "DELETE FROM items WHERE name LIKE 'e2e-row%'"
   ```

## What the cycle catches that ConnCase cannot

- Which params the write-access plug actually requires (real case: the
  `workspace` param was mandatory on feedback/delete endpoints — invisible
  behind the mock).
- Live dedupe/search/auth behavior across the full plug stack.
- JSON shape of non-trivial column types after real encoding.
- Cross-workspace scoping end-to-end (the 404 — and the regression test
  should also assert the foreign row is untouched, not just the status).

## Notes

- Expect writes to be exercised with a dedicated e2e marker (a name prefix
  like `e2e-`) so cleanup is a single `DELETE ... WHERE ... LIKE`.
- The cycle runs against the dev DB — that is why cleanup is mandatory, not
  optional.

## Verification

- All five statuses observed as expected (create 201/200, duplicate 4xx or
  defined contract, search 200 with the seeded row, 401, 404).
- `psql -c "SELECT count(*) ..."` after cleanup → 0 e2e rows.
- Server process gone (`kill %1`; confirm the port is free).
