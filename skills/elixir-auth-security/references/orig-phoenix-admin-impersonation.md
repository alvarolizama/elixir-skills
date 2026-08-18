---
name: phoenix-admin-impersonation
description: "Use when adding user impersonation to a Phoenix app."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [phoenix, liveview, auth, impersonation, admin, session]
    related_skills: [phoenix-security-audit, test-driven-development]
---

# Phoenix Admin Impersonation ("Ver como")

Add a "view dashboard as this user" capability to a Phoenix/LiveView admin
panel WITHOUT touching downstream auth code. Session-swap pattern with
guards, persistent banner and audit trail. Proven in MyApp (2026-07-27).

## Core pattern: swap `:user_id`, keep `:impersonator_id`

The session's `:user_id` ALWAYS holds the *effective* user — plugs, LiveView
`on_mount` hooks, Presence trackers and every existing assign keep working
with zero changes. The original admin's id lives in a second session key:

- Start: `put_session(:impersonator_id, admin.id) |> put_session(:user_id, target.id)`
- Stop: `delete_session(:impersonator_id) |> put_session(:user_id, impersonator_id)`

Do NOT invent a parallel "effective user" assign that every LiveView must
learn about — that forks the auth model and rots immediately.

## Controller actions + routes

Two actions on the session controller, routes in the plain `:browser`
pipeline (NOT behind a `require_admin` plug):

- `POST /impersonate/:user_id` — starts impersonation.
- `DELETE /impersonate` — stops it. Runs while the session points at the
  impersonated (non-admin) user, so **no admin plug can guard it** — put ALL
  guards inside the controller actions.

### Guard matrix (start action, evaluated in this order)

1. Unauthenticated → redirect `/login`.
2. `get_session(:impersonator_id)` present → refuse (no nesting).
3. `current_user.global_role != "admin"` → refuse.
4. Target not found → redirect with error flash.
5. Target == self → refuse.
6. Target is the root/bootstrap admin (env email, e.g.
   `MY_APP_ADMIN_EMAIL` fallback `admin@MyApp.local`) → refuse.

Every refusal leaves the session untouched — assert that in tests.

## Audit trail

Write audit entries for BOTH directions, always with the REAL admin as
actor: `impersonate.start` on start (actor = admin, entity = target) and
`impersonate.stop` on stop (actor = impersonator_id from session, entity =
current effective user).

## Surfacing state: assigns + banner

- Auth plug (`fetch_current_user`): `assign(:impersonator, ...)` from
  `get_session(:impersonator_id)` (nil otherwise).
- `on_mount` hooks (all three: default / require_authenticated /
  require_admin): `assign_new(:impersonator, ...)`. Remember LiveView
  sessions use STRING keys (`session["impersonator_id"]`), plugs use atoms —
  read both.
- Layout component: add `attr :impersonator, :map, default: nil` and render
  a `:if={@impersonator}` banner (warning color) above the topbar:
  "Viendo como **{effective email}** — sesión de {impersonator email}" plus a
  `<.link href={~p"/impersonate"} method="delete">Volver a mi cuenta</.link>`.
- Update EVERY `<Layouts.dashboard ...>` call site to pass
  `impersonator={@impersonator}` — grep for the exact call text and batch it;
  they are usually identical one-liners (12 sites in MyApp). Don't forget
  the `@doc` example inside the layout module itself.
- Users list: per-row `<.link method="post" href={~p"/impersonate/#{user.id}"}>`,
  hidden for self and root admin. Session changes need a REAL HTTP request —
  a `phx-click` LiveView event cannot touch the session.

## Test checklist (TDD red first)

Controller: happy path (session keys swapped + audit row), banner visible on
a subsequent GET, non-admin refused, unauthenticated → login, self refused,
nesting refused (session still points at first target), unknown id refused,
stop restores original user + audit row, stop-when-not-impersonating is a
no-op with flash. LiveView: impersonate link present for other users, absent
for self and root admin.

Gotcha: the root admin email usually ALREADY EXISTS in the test DB (seeds
run in test env too) — fetch it with `get_user_by_email/1` instead of
registering a duplicate (unique constraint failure).

## Pitfalls

- `mix precommit` (compile --warnings-as-errors) flags unused vars in the
  guard clauses (`_admin` for the nil-target clause).
- If the layout file already carries unrelated uncommitted WIP, split hunks
  with `git add -p` (see git-history-surgery) — never sweep it into the
  impersonation commit.

## Also see

- `references/admin-only-route-protection.md` — protecting a plain LiveView
  route behind a `require_admin` plug / `:admin` pipeline WITHOUT impersonation
  (admin CRUD UI, `list_contexts` vs current-scope, and the module-attr-ordering,
  `handle_event` clause-grouping, and `CoreComponents.button`-type gotchas that
  break `mix precommit`).
