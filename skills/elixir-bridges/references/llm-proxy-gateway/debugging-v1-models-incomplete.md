# Debugging incomplete `/v1/models` responses

Session: 2026-07-28. Symptom: `GET /v1/models` returns fewer models than
expected — some aliases are missing from the list.

## Call chain

```
GET /v1/models
  → ProxyController.models/1              (proxy_controller.ex:49)
    → Router.models_for(member)           (routing/router.ex:132)
      → Providers.list_accessible_aliases(team_member)  (providers.ex:443)
        → UNION(
            team_model_aliases WHERE team_id,            -- team grants
            team_member_extra_aliases WHERE team_member_id -- individual grants
          )
        → JOIN model_aliases
        → Repo.all()
```

The `ApiAuth` plug (`plugs/api_auth.ex`) resolves the bearer token to a
`TeamMember` with `:team`, `:user`, `:api_key` preloaded
(`Accounts.get_team_member_by_api_key/1`).

## What it filters on (and what it does NOT)

| Check | Applied? |
|-------|----------|
| Team grant (`team_model_aliases` row) | ✅ Yes — primary filter |
| Extra alias grant (`team_member_extra_aliases` row) | ✅ Yes — unioned in |
| Alias has `model_providers` configured | ❌ No |
| Alias has active credentials | ❌ No |
| Circuit breaker state | ❌ No — breaker only runs in `route/3` |
| Caching (ETS, process dict) | ❌ No — direct Postgres query every call |

**Key insight:** `/v1/models` returns every alias the team/member has been
*granted*, regardless of whether it has working providers behind it. An alias
with zero `model_providers` or all-disabled credentials will still appear in
the list. Conversely, if an alias is missing from the list, the grant is the
problem — not the provider/credential state.

## Diagnostic steps (in order)

1. **Verify the API key and team.** If `/v1/models` returns 200 at all, the
   key is valid and the membership is active. The team_member's `team` must be
   preloaded — `Router.models_for/1` calls `maybe_preload_team/1` which
   force-reloads if `team.id` is nil. If the team is genuinely nil in the DB,
   `list_accessible_aliases/1` will crash on `team_member.team.id` (500, not
   a short list).

2. **Check team grants directly:**
   ```sql
   SELECT ma.name, ma.display_name, ma.context_window
   FROM team_model_aliases tma
   JOIN model_aliases ma ON ma.id = tma.model_alias_id
   WHERE tma.team_id = '<team-uuid>';
   ```
   Compare with what `/v1/models` returns. If a model is missing here, it was
   never granted to the team — add it via `/dashboard/models`.

3. **Check extra alias grants for the specific member:**
   ```sql
   SELECT ma.name
   FROM team_member_extra_aliases tmea
   JOIN model_aliases ma ON ma.id = tmea.model_alias_id
   WHERE tmea.team_member_id = '<member-uuid>';
   ```
   A member may have access to models their team doesn't, via this table.

4. **If the grant exists but the model still doesn't appear**, check that the
   `model_alias` row itself exists and wasn't deleted:
   ```sql
   SELECT * FROM model_aliases WHERE name = '<missing-model-name>';
   ```
   The join in `list_accessible_aliases/1` is an inner join — if the alias
   row was deleted but the `team_model_aliases` row wasn't (orphaned grant),
   the alias won't appear. This would be a data integrity issue.

5. **If the API key was recently rotated or the member moved teams**, the
   `team_id` in the query changes. Verify:
   ```sql
   SELECT tm.id, tm.team_id, tm.status, ak.key_prefix
   FROM team_members tm
   JOIN api_keys ak ON ak.team_member_id = tm.id
   WHERE ak.key_hash = '<sha256-of-token>';
   ```

## Relationship to `debugging-no-available-provider.md`

These two references are complementary:

- **This file:** `/v1/models` returns fewer models than expected → check
  team grants and `team_model_aliases` table.
- **`debugging-no-available-provider.md`:** `/v1/models` returns the model
  fine, but `POST /v1/chat/completions` returns 503 `no_available_provider`
  → check provider/credential state and circuit breaker.

The diagnostic split is: if the model is **missing from the list**, it's a
grant problem (this file). If the model is **in the list but can't route**,
it's a provider/credential/breaker problem (the other file).

## Common causes ranked by likelihood

1. **Alias was never granted to the team** — someone forgot to add it in
   `/dashboard/models` → `team_model_aliases` table.
2. **API key belongs to a different team member** — rotated key, different
   team, or the member was moved.
3. **Alias row was deleted but grant row orphaned** — data integrity issue,
   rare but possible if cascades aren't set up.
4. **Team not preloaded on the member struct** — `maybe_preload_team/1`
   should handle this, but if the team association is genuinely nil in the
   DB (member has no team), it crashes rather than returning a short list.
