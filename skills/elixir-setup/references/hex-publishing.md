# Hex package publishing (unattended-safe)

Publishing an Elixir library to hex.pm: metadata, auth, the publish command,
and the interactive-prompt traps that hang or crash unattended runs.

## Pre-publish checklist

1. **Name availability** — `curl -s -o /dev/null -w "%{http_code}" https://hex.pm/packages/<name>`; `404` = available.
2. **`mix.exs` metadata:**

   ```elixir
   defp package do
     [
       name: "mypkg",
       licenses: ["MIT"],
       maintainers: ["Your Name"],
       files: ~w[lib mix.exs README.md LICENSE .formatter.exs],
       links: %{"GitHub" => "...", "Docs" => "https://hexdocs.pm/mypkg"}
     ]
   end
   ```

   - `files:` must list `LICENSE`, and the file must exist INSIDE the package
     dir — in a monorepo, copy the root LICENSE in before publishing.
   - Publish FROM the package subdir (`cd pkg/ && mix hex.publish`), never the
     repo root.
3. **`elixir:` requirement** — floor set by the strictest dep (check
   `deps/*/mix.exs`), not just what you run.
4. **`ex_doc` for hexdocs** — `{:ex_doc, "~> 0.34", only: :dev, runtime: false}`.
5. **Verify first:** `mix compile --warnings-as-errors` + `mix test` +
   `mix hex.build` dry-run (inspect the tarball file list).
6. **GitHub link must exist** — push the repo BEFORE publishing.

## Fresh-project compile verification (optional deps)

Local `mix compile --warnings-as-errors` is NOT proof downstream compiles —
your dev env has every optional dep; consumers get only non-optional ones.
Known failure modes that pass locally and break downstream:

- **Struct patterns on optional-dep structs** (`%Decimal{}`, `%Date{}`) —
  struct expansion needs the module at COMPILE time. Match
  `%{__struct__: mod}` and dispatch via `apply/3`.
- **Unguarded module references to optional-dep modules** (`@behaviour Plug`)
  — wrap in `if Code.ensure_loaded?(Plug.Conn) do ... else <stub> end`; guard
  supervision children with `Code.ensure_loaded?(Bandit)` + a clean
  `Logger.error` naming the dep to add (never a boot crash).

Smoke procedure before EVERY publish:

```bash
cd /tmp && mix new smoke && cd smoke
# add ONLY {:pkg, path: "..."} — NOT the optional deps
mix deps.get && mix compile     # MUST compile
# boot with the documented config — MUST log a clean error, not crash
```

After publishing, repeat from the registry (`{:pkg, "~> X.Y"}`) — path deps
mask failures because your dev env has everything.

## The interactive prompt trap (CRITICAL)

`mix hex.publish` asks up to three interactive questions:

1. **Owner selection** (FIRST publish, account belongs to an org):
   `[1] Yourself [2] <org>`.
2. **Proceed confirmation**: `Y`/`n`.
3. **2FA code** (accounts with TOTP): asked mid-publish, AFTER
   `Publishing package...`. OTPs expire in ~30s.

**CRITICAL — get the OTP BEFORE launching.** You cannot inject it mid-stream.
Piping only `Y\n` leaves stdin exhausted at the 2FA prompt, and the process
crashes with `(FunctionClauseError) no function clause matching in
String.trim/1: :eof`. Correct sequences:

```bash
printf 'Y\n<otp>\n' | mix hex.publish package           # normal publish
printf '1\nY\n<otp>\n' | mix hex.publish package        # first publish, owner=yourself
```

- **`yes | mix hex.publish` HANGS FOREVER at 100%+ CPU.** `yes` answers "Y" to
  the owner prompt, which is invalid input, and Hex re-prompts infinitely.
- **No stdin at all** → the same `String.trim/1: :eof` crash — that crash MEANS
  "stdin exhausted before all prompts were answered" (missing owner answer or
  missing OTP).
- `mix hex.publish` (no args) publishes package AND docs (slow first time);
  `mix hex.publish package` skips docs — use it to unblock a release.

## Auth and key permissions

- `mix hex.user auth` — interactive (email + password), generates a
  full-permission key; the agent cannot run it for the user.
- **`mix hex.user whoami` — run as pre-flight check BEFORE publish.** If the
  stored token has expired, publish silently enters an OAuth devICE flow
  mid-run and your piped `Y` is consumed by its auth prompt instead of
  "Proceed?" (see below).
- **`Publishing failed: key not authorized for this action`** = the stored
  key is read-only (or an org key without publish rights). Fix: have the user
  re-run `mix hex.user auth`, or create a key at
  https://hex.pm/dashboard/keys with **API write** permission and publish with
  `HEX_API_KEY=<key> mix hex.publish package`.

### Token expired → device flow eats your piped `Y`

Stored token expired → `mix hex.publish` enters device flow mid-run:

```
No authenticated user found. Do you want to authenticate now? [Yn]
To authenticate, visit: https://hex.pm/oauth/device?user_code=XXXX
Your verification code: XXXX-XXXX
Waiting for authentication...
You are authenticated!
Proceed? [Yn]
```

If you piped `printf 'Y\n<otp>\n'`, the `Y` answers "authenticate now?", the
user authenticates in the browser, and then the "Proceed?" prompt finds stdin
exhausted — publish silently fails.

**Recovery:** (1) complete the device flow (token is now stored), (2) verify
with `mix hex.user whoami`, (3) re-run `printf 'Y\n<otp>\n' | mix hex.publish
package` with a FRESH OTP — this time the first prompt is "Proceed?".

## Versioning

- Bump `version:` in `mix.exs`, re-run the checklist, publish again.
- **Also bump hardcoded versions in code** — Server/SDK modules often carry
  their own version string that doesn't follow mix.exs. Grep for the old
  version outside mix.exs before republishing.
- A publish is **irreversible** — `--revert` only works within 1 hour.

## Post-publish

```bash
curl -s https://hex.pm/packages/<name>            # 200
curl -s https://hex.pm/packages/<name>/<version>  # 200
```

Then test the actual install path: fresh project, dep from hex (NOT path),
compile.

## Plug halt gotcha (library packaging)

Any plug that calls `send_resp` (directly or via a delegated plug) MUST call
`Plug.Conn.halt/1` afterward — otherwise the endpoint pipeline continues and
the Router raises `NoRouteError` for the already-answered path:

```elixir
def call(%Plug.Conn{request_path: path} = conn, opts) do
  if path == @mcp_path do
    conn |> InnerPlug.call(opts) |> Plug.Conn.halt()   # ← CRITICAL
  else
    conn
  end
end
```

Generalizable rule: wrapping third-party plugs that handle their own
responses — never assume the inner plug halts for you.

## Verification

```bash
mix hex.user whoami                                  # pre-flight auth check
mix compile --warnings-as-errors && mix test
mix hex.build                                        # dry-run, inspect file list
curl -s -o /dev/null -w "%{http_code}" https://hex.pm/packages/<name>   # 200 after publish
```