# MyApp: `delete_model_provider` FK constraint

## Symptom

LiveView admin crashed when deleting a model provider:

```
** (Ecto.ConstraintError) constraint error when attempting to delete struct:
* "model_pricing_model_provider_id_fkey" (foreign_key_constraint)
```

The handler `MyAppWeb.ModelsLive.handle_event("delete_model_provider", ...)` called `Providers.delete_model_provider/1`, which did a plain `Repo.delete(model_provider)` without cleaning up dependent `model_pricing` rows.

## Investigation

1. `search_files` found `delete_model_provider` in `lib/my_app_web/live/models_live.ex:297` and `lib/MyApp/providers.ex:210`.
2. The context function was a single `Repo.delete/1` with no cascade handling.
3. The schema `ModelProvider` had `has_many :model_pricing, MyApp.Providers.ModelPricing` without `on_delete`.
4. The migration `CreateModelPricing` declared the FK without `on_delete: :delete_all`.
5. A sibling function, `delete_provider/1`, already used an explicit transaction to delete dependent rows first, so the pattern existed in the same file.

## Fix

1. Added a migration `AddCascadeDeleteModelPricingFk` that drops and re-adds the FK with `on_delete: :delete_all`.
2. Added `on_delete: :delete_all` to the `has_many :model_pricing` association in `ModelProvider`.
3. Rewrote `delete_model_provider/1` to delete `model_pricing` rows first inside a `Repo.transaction`.
4. Added a regression test in `test/MyApp/providers_test.exs` that creates a `ModelProvider` with a `ModelPricing` child and asserts the delete succeeds and leaves no child rows.

## Verification

- `mix ecto.migrate`
- `mix test test/MyApp/providers_test.exs` — 29 passed
- `mix precommit` — 595 passed

## Key Takeaway

A delete constraint error usually means a missing cascade rule at one of three layers: context, schema, or migration. Fixing only the context or only the schema leaves the DB unprotected; always enforce the cascade at the migration level too.
