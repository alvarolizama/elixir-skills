# Elixir 1.20 / Ecto 3.14 runtime gotchas (verified)

Verified against Elixir 1.20.1 / OTP 29 / Ecto 3.14.1 while building the
extools plugin (static eval, schema introspection, ExUnit parsing). These
are real transcripts, not speculation.

## 1. Eval wrapper: `(begin ... end)` is invalid — use `(fn -> ... end).()`

```elixir
# INVALID — MismatchedDelimiterError on the `end)` line:
result = (begin
  1 + 1
end)

# VALID — zero-arg fn groups multiple statements into one expression:
try do
  result = (fn ->
    x = 10
    y = 32
    x + y
  end).()
  IO.puts("~RESULT_START~")
  IO.puts(inspect(result, limit: :infinity, pretty: true))
  IO.puts("~RESULT_END~")
rescue
  e ->
    IO.puts("~RESULT_START~")
    IO.puts("error: " <> Exception.message(e))
    IO.puts("~RESULT_END~")
end
```

Runtime errors (e.g. `1/0`) are caught by the rescue and come back as
`error: bad argument in arithmetic expression` — the VM survives.

## 2. `mix run` vs `mix run --no-start`

Plain `mix run -e` on a Phoenix app boots EVERYTHING on every eval —
observed output during a simple introspection eval:

```
[debug] Adding job            # Oban inserting jobs
[info] Running DranWeb.Endpoint with Bandit 1.12.0 at 127.0.0.1:4000
```

That eval took 4.6s vs 0.5s with `--no-start`. Default to `--no-start`;
only start the app (`start_app` flag) when code needs the supervision
tree (Repo queries, GenServer calls).

Modules ARE loadable under `--no-start`:

```elixir
Application.load(:my_app)                                   # makes spec available
Application.spec(:my_app, :modules)                          # => 114 modules
Code.ensure_loaded?(my_app.Brain.Page)                       # => true
```

`:code.all_loaded()` does NOT see these modules in a fresh `--no-start` VM.

## 3. Ecto 3.14 removed `__schema__(:types)`

```elixir
my_app.Brain.Page.__schema__(:types)
# ** (FunctionClauseError) no function clause matching in my_app.Brain.Page.__schema__/1

# Supported 1-arity queries (verified): :query, :source, :fields,
# :associations, :embeds, :primary_key
# NOT supported: :types, :type

# Replacements (both verified):
my_app.Brain.Page.__schema__(:type, :title)   # => :string  (2-arity)
Map.take(my_app.Brain.Page.__changeset__(), [:title, :tags, :embedding])
# => %{title: :string, tags: {:array, :string}, embedding: Pgvector.Ecto.Vector}
```

Also: `Ecto.Migration.SchemaMigration` exports `__schema__/1` but raises on
most queries — wrap every module's extraction in try/rescue and skip nils.

## 4. ExUnit output — Elixir 1.20 format

`mix test --trace` on 1.20 (note: no per-test pass/fail markers; the `\r`
separates the in-progress line from its completed overwrite):

```
Running ExUnit with seed: 980341, max_cases: 1


MyAppWeb.ErrorJSONTest [test/my_app_web/controllers/error_json_test.exs]
  * test renders 404 [L#4]\r  * test renders 404 (7.4ms) [L#4]
  * test renders 500 [L#8]\r  * test renders 500 (0.7ms) [L#8]

Finished in 0.04 seconds (0.02s async, 0.02s sync)

Result: 5 passed
```

With a failure (real transcript):

```
ExtoolsTmpFailureTest [test/extools_tmp_failure_test.exs]
  * test this one passes [L#8]\r  * test this one passes (0.00ms) [L#8]
  * test this one fails on purpose [L#4]\r  * test this one fails on purpose (0.4ms) [L#4]

  1) test this one fails on purpose (ExtoolsTmpFailureTest)
     test/extools_tmp_failure_test.exs:4
     Assertion with == failed
     code:  assert 1 == 2
     left:  1
     right: 2
     stacktrace:
       test/extools_tmp_failure_test.exs:5: (test)


Finished in 0.00 seconds (0.00s async, 0.00s sync)

Result: 1/2 passed
Failed: 1 test
```

Parser rules that follow from this:

- Split lines on `[\r\n]+` (the `\r` overwrite becomes two lines when piped).
- Module header: `^(Module.Name) \[(test/path_test.exs)\]$`
- Completed test: `^\s*\* test (.+?) \(([\d.]+)\s*(ms|µs|s)\) \[L#(\d+)\]` —
  status defaults to pass; failures are only in the `N) name (Module)`
  section. Cross-reference by `module::name` (strip the `test ` prefix
  consistently — the failure header drops it, the trace line keeps it).
- Summary: `Result: (\d+)(?:/(\d+))? passed` + optional `Failed: (\d+) tests?`.
- Python: any `^...` regex used with `.search()` over the WHOLE output needs
  `re.MULTILINE` or it never matches (this bug cost a debugging cycle).
- Always run `mix test --trace` — without it, 1.20 prints only dots + the
  `Result:` line (no per-test detail). Note `--trace` forces `max_cases: 1`.
- Keep the legacy parser (`N tests, M failures` / dot formatter) as fallback
  for older Elixir versions; dispatch on whether `Result:` or `* test`
  patterns are present.

## 5. Syntax landmines in GENERATED Elixir code

These three parse failures only bite when a tool generates Elixir source —
hand-written lib code never hits them. All verified on Elixir 1.20.1.

### 5a. `private` is a reserved word — not a valid variable name

```elixir
# INVALID — SyntaxError (points confusingly at the next line):
lv_routes = Enum.filter(all_routes, fn r ->
  private = Map.get(r, :private) || %{}
  ...
end)

# VALID:
priv = Map.get(r, :private) || %{}
```

The error location is misleading (`nofile:10:29` pointed at the `if` on the
NEXT line, not at `private`). When a generated snippet fails to parse at a
line that looks valid, check the surrounding lines for reserved words used
as variables.

### 5b. Trailing `if` after a `?`-suffixed call does NOT parse

```elixir
# INVALID — "syntax error before: 'if'":
Code.ensure_loaded?(router) if router

# VALID:
if router, do: Code.ensure_loaded!(router)
```

Trailing `if` works after plain calls (`IO.puts("x") if flag`) but not
after a `fun?()` call in this position. Just avoid trailing-if in
generated code — always use `if cond, do: expr`.

### 5c. One-liner `if ..., do: ..., else: ...` IS valid inside `fn`

```elixir
# VALID (verified) — don't "fix" these into multi-line ifs:
plug_str = if is_atom(plug), do: Atom.to_string(plug), else: inspect(plug)
```

## 6. `mix test --cover` — Elixir 1.20 pipe-table format

Real output (MyApp, 1.20.1):

```
|     75.00% | MyAppWeb.Layouts        |
|    100.00% | MyApp                   |
|------------|-----------------------------|
|     35.68% | Total                       |

Coverage test failed, threshold not met:

    Coverage:   35.68%
    Threshold:  90.00%
```

Parser regex: `^\|\s*([\d.]+)%\s*\|\s*([^|]+?)\s*\|` (keep the old
`^\s*([\d.]+)%\s+(.+)` as fallback). The threshold failure makes the task
exit NON-ZERO even when all tests pass — that's a valid result state
(`success: false` + parsed percentages), not a tool error.

## 7. Phoenix router detection failure modes (1.8)

Both verified against my_app (Phoenix 1.8):

- `lib/dran_web.ex` mentions `use Phoenix.Router` inside its `__using__`
  macro quote — a naive `use Phoenix.Router` text scan returns `DranWeb`
  (no `__routes__/0`). Only accept module names ending in `Router` or
  filenames containing `router`.
- The REAL router (`lib/dran_web/router.ex`) says `use DranWeb, :router` —
  no literal `use Phoenix.Router` anywhere in the file, so the text scan
  finds NOTHING. The `Application.spec(app, :modules)` +
  `function_exported?(mod, :__routes__, 0)` fallback is the only reliable
  path for Phoenix 1.8 apps; it works under `mix run --no-start` with
  `Application.load/1` first.

## 8. Elixir 1.20 compile-warning trivia (fails `--warnings-as-errors`)

All hit while compiling the extools hex package:

- `String.slice(str, 3..-2)` → "3..-2 has a default step of -1, please
  write 3..-2//-1 instead". Ranges with negative direction need the
  explicit `//-1` step.
- Heredoc content must be indented to the same level as the closing `"""`
  ("outdented heredoc line") — `mix format` fixes it automatically.
- Underscored variable used after being set
  (`{_key, {_lvl, _meta, msg}}` then `level_to_int(_lvl)`) → "the
  underscored variable is used after being set" — rename to `lvl`.
- `:dbg.stop_clear/0` is deprecated (OTP 26+; removal noted for OTP 27) —
  use `:dbg.stop/0`. `:dbg` itself needs `:runtime_tools` in
  `extra_applications` or every `:dbg.*` call warns "module :dbg is not
  available".
