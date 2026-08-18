---
name: hex-package-publishing
description: "Use when publishing Elixir packages to hex.pm."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [elixir, hex, hexpm, publishing, package, release]
    related_skills: [elixir-mix-build, phoenix-release-deploy]
---

# Hex Package Publishing

Publishing an Elixir library to hex.pm: metadata, auth, the publish command,
and the interactive-prompt traps that hang unattended runs.

## When to Use

- First-time `mix hex.publish` of a package
- Version-bump re-publish
- "key not authorized for this action" errors
- `mix hex.publish` hanging or burning CPU with no output
- Packaging a library that lives in a **subdirectory of a monorepo**

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

   - **`files:` must list `LICENSE`** and the file must exist **inside the
     package dir** — in a monorepo the LICENSE usually lives at the repo
     root; copy it into the package subdir before publishing.
   - The `files:` list is also what keeps a monorepo tarball clean — publish
     FROM the package subdir (`cd hex/ && mix hex.publish`), never the repo
     root.
3. **`elixir:` requirement** — set the floor to what your strictest dep
   requires (check `deps/*/mix.exs`), not just what you run. Note the actual
   tested version in a comment (e.g. `# Tested on 1.20, floor set by hermes_mcp`).
4. **`ex_doc` for hexdocs** — `{:ex_doc, "~> 0.34", only: :dev, runtime: false}`.
   Without it, `mix hex.publish` skips docs (fine) but hexdocs.pm stays empty.
5. **Verify first:** `mix compile --warnings-as-errors` clean + `mix test`
   green + `mix hex.build` dry-run (inspect the file list in the tarball).
6. **GitHub link should exist** — push the repo BEFORE publishing or the
   hex.pm page links to a 404: `gh repo create <user>/<repo> --public --source . --push`.

## Fresh-project compile verification (optional deps)

Local `mix compile --warnings-as-errors` is NOT proof the package compiles
for users — your dev env has every optional dep installed; downstream gets
only non-optional ones. Two failure modes that pass locally and break
downstream (both shipped in extools 0.1.0 → forced an immediate 0.1.1):

- **Struct patterns on optional-dep structs** (`%Decimal{}`, `%Date{}`) —
  struct expansion needs the module at COMPILE time. Match
  `%{__struct__: mod}` instead and dispatch with atom comparison +
  `apply/3` (`mod == Decimal -> apply(Decimal, :to_string, [v])`).
- **Unguarded module references to optional-dep modules** (e.g.
  `@behaviour Plug` when bandit/plug is optional) — wrap the whole module
  in `if Code.ensure_loaded?(Plug.Conn) do ... else <stub> end`; guard
  supervision children with `Code.ensure_loaded?(Bandit)` + a clean
  `Logger.error` telling the user which dep to add (never a boot crash).

Smoke procedure before EVERY publish:

```bash
cd /tmp && mix new smoke && cd smoke
# add ONLY {:pkg, path: "..."} — NOT the optional deps
mix deps.get && mix compile     # MUST compile
# boot with the documented config — MUST log a clean error, not crash
# then add the optional dep and test the full feature path end-to-end
```

And AFTER publishing, repeat from the registry (`{:pkg, "~> X.Y"}`) —
path-dep testing masks the failure because your dev env has everything.

## The interactive prompt trap (CRITICAL)

`mix hex.publish` asks up to **three** interactive questions:

1. **Owner selection** (FIRST publish of a package, when the account
   belongs to an org): `[1] Yourself [2] <org>` — expects `1` or `2`.
   Not asked again once the package exists.
2. **Proceed confirmation** — expects `Y`/`n`.
3. **2FA code** (accounts with TOTP): `Enter your 2FA code:` — asked
   mid-publish, AFTER `Publishing package...`. OTPs expire in ~30s.

   **CRITICAL — get the OTP BEFORE launching the command.** You cannot
   inject it mid-stream: once the process is running, stdin is whatever
   you piped at launch time. If you pipe only `Y\n` (proceed) without
   the OTP, the 2FA prompt appears, stdin is exhausted, and the process
   crashes with `(FunctionClauseError) no function clause matching in
   String.trim/1: :eof`. The correct sequence is:

   1. Ask the user for their current 2FA code (clarify).
   2. Pipe everything in one shot:
      `printf 'Y\n<otp>\n' | mix hex.publish package`
      (or `printf '1\nY\n<otp>\n'` for first-publish with owner selection).
   3. On "Invalid two-factor authentication code" the task re-prompts
      and a fresh code can follow in the same run — but the OTP must
      still be in the original pipe. If the pipe is exhausted, re-run
      with a fresh OTP.

- **`yes | mix hex.publish` or `yes Y | ...` HANGS FOREVER at 100%+ CPU.**
  `yes` answers "Y" to the owner prompt, which is invalid input, and Hex
  re-prompts in an infinite loop. This looks exactly like a frozen/network
  hang — check for the owner prompt before blaming the network.
- **Pipe exact answers in order:** `printf '1\nY\n' | mix hex.publish package`
  (owner=yourself, then proceed).
- With no stdin at all, the run crashes with
  `(FunctionClauseError) no function clause matching in String.trim/1: :eof`
  — that crash MEANS "stdin was exhausted before all prompts were answered".
  Two common causes: (a) first-publish and the owner/org prompt wasn't
  answered (pipe `1\n` for "yourself"), or (b) 2FA is enabled and you
  piped only `Y\n` without the OTP — the 2FA prompt appears, stdin is
  empty, crash. Fix: include ALL answers in the pipe, including the OTP
  (which you must obtain from the user BEFORE launching the command).
- `mix hex.publish` (no args) publishes package AND docs; the docs build can
  be slow on first run. `mix hex.publish package` skips docs — use it to
  unblock a release and publish docs separately later.

## Auth and key permissions

- `mix hex.user auth` — interactive (asks email + password), generates a
  **full-permission** key. The agent cannot run this for the user (password).
- `mix hex.user whoami` — verify auth state. **Run this as a pre-flight
  check BEFORE `mix hex.publish`** — if the stored token has expired, the
  publish command enters an OAuth device flow mid-run and your piped stdin
  (`printf 'Y\n<otp>\n'`) gets consumed by the device flow prompts, not the
  publish prompts. See "Token expired → device flow" section below for the
  full recovery sequence.
- **`Publishing failed: key not authorized for this action`** = the stored
  key is read-only (or an org key without publish rights on the personal
  namespace). Fixes: re-run `mix hex.user auth` (user does it), OR have the
  user create a key at https://hex.pm/dashboard/keys with **API write**
  permission and publish with `HEX_API_KEY=<key> mix hex.publish package`.

### Token expired → device flow auth eats your piped `Y` (CRITICAL)

When the stored hex token has expired (happens silently — `mix hex.user whoami`
may still report the username from cached state, but the publish call fails
with "Token refresh failed. Please re-authenticate."), `mix hex.publish`
enters **device flow authentication** mid-run. It prints:

```
No authenticated user found. Do you want to authenticate now? [Yn]
To authenticate, visit: https://hex.pm/oauth/device?user_code=XXXX
Your verification code: XXXX-XXXX
Waiting for authentication...
You are authenticated!
Proceed? [Yn]
```

**The trap:** if you piped `printf 'Y\n<otp>\n'` expecting the `Y` to answer
the "Proceed?" prompt, the `Y` is consumed by the FIRST prompt
("Do you want to authenticate now?"). The user authenticates in the browser,
hex prints "You are authenticated!", then asks "Proceed?" — but stdin is
exhausted (the OTP was the next token, not a second `Y`). The publish silently
fails; `curl -s -o /dev/null -w "%{http_code}" https://hex.pm/packages/<name>/<version>`
returns 404.

**Correct recovery sequence:**
1. The device flow auth completed (user authenticated in browser) — the
   token is now stored. Verify with `mix hex.user whoami`.
2. Re-run the publish with a FRESH OTP: `printf 'Y\n<otp>\n' | mix hex.publish package`.
   This time the first prompt is "Proceed?" (no re-auth needed), `Y` answers
   it, and the OTP answers the 2FA prompt.
3. Verify with `curl` that the version returns 200.

**Pre-flight check:** run `mix hex.user whoami` before the first publish
attempt. If it fails or the token is stale, have the user run
`mix hex.user auth` (interactive — agent can't do it) BEFORE attempting the
publish, so the device flow doesn't ambush your piped stdin.

## Versioning

- Bump `version:` in the package `mix.exs`, re-run the checklist, publish again.
- **Also bump hardcoded versions in code.** Server/SDK modules often carry
  their own version string (e.g. `use Hermes.Server, version: "0.1.0"`) that
  does NOT follow mix.exs automatically — the MCP handshake then reports the
  stale version forever. Grep for the old version string outside mix.exs
  before republishing (`grep -rn "0.1.0" lib/`).
- A publish is **irreversible** — `mix hex.publish --revert` only works
  within 1 hour of publishing.

## Post-publish

- Verify: `curl -s https://hex.pm/packages/<name>` returns 200.
- Docs land at `https://hexdocs.pm/<name>` (if ex_doc ran).
- Consumers install with `{:mypkg, "~> 0.1"}` — check the README install
  snippet matches the published version.
- **Test the actual install path** — after publishing, create a fresh mix
  project, add the dep from hex (NOT path), and verify it compiles. Your dev
  env has optional deps locally; downstream gets only what `mix.exs` declares.
  See "Fresh-project compile verification" above.

## Pitfall: Plug that delegates to another plug must halt the conn

**Symptom:** a plug library that wraps another plug (e.g. `MCPPlug.call/2`
inside `Extools.call/2`) works — the response is sent (200 in logs) — but
the downstream Phoenix Router also processes the request and raises
`NoRouteError` for the plug's path.

**Root cause:** the inner plug calls `send_resp/3` but never calls
`Plug.Conn.halt/1`. In a Phoenix endpoint, the plug pipeline continues
after a non-halted response — so the Router receives the already-sent conn,
tries to match the path, and crashes.

**Fix:** in the wrapper plug's `call/2`, always `halt` the conn after
delegating:

```elixir
def call(%Plug.Conn{request_path: path} = conn, opts) do
  if path == @mcp_path do
    conn
    |> InnerPlug.call(opts)
    |> Plug.Conn.halt()   # ← CRITICAL: stop the pipeline here
  else
    conn
  end
end
```

**Generalizable rule:** any plug that calls `send_resp` (directly or via a
delegated plug) MUST call `Plug.Conn.halt/1` afterward. Without halt, the
next plug in the endpoint pipeline gets the conn and may raise. This is
especially easy to miss when wrapping third-party plugs that handle their
own responses — you can't assume the inner plug halts for you.

**Workaround for consumers (if you can't patch the library):** add a
`halt_if_sent` plug immediately after the library's plug in your endpoint:

```elixir
if Mix.env() == :dev do
  plug Extools
  plug :halt_if_sent
end

plug MyAppWeb.Router

defp halt_if_sent(%Plug.Conn{state: state} = conn, _opts)
     when state in [:sent, :chunked, :file] do
  Plug.Conn.halt(conn)
end
defp halt_if_sent(conn, _opts), do: conn
```

This was shipped as extools 0.2.0 (missing halt) → 0.2.1 (fixed). The fix
is a one-liner: `|> Plug.Conn.halt()` after the delegated `call`.
