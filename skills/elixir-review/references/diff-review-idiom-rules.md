# Diff Review Idiom Rules — Full Catalog

Distilled code-review rulebook for Elixir/Phoenix codebases (LiveView + Ecto
+ gettext + ExMachina). Every rule has a **severity**, a **why**, an
**anti-pattern**, and the **correct form**. Rule IDs are stable — cite them
in review comments (`EX-01: use multiple clauses instead of nested case`).

Severity legend:

- **high** — merge blocker: bugs, leaks, broken contracts, data-loss risk.
- **medium** — should fix: readability, testability, idiomatic Elixir.
- **low** — nit: optional polish, style preference.

---

## Elixir Style / Idioms

### EX-01 — Prefer pattern matching with multiple clauses over nested `case`
**Severity:** medium

**Why:** Conditions that test specific values (`nil`, boolean flags) read
better as function clauses: less indentation, early return, linear happy
path.

**Anti-pattern:**

```elixir
def get_current_columns(assigns) do
  case assigns do
    %{alternate_flow: true} ->
      case assigns.selected_bucket do
        nil -> []
        bucket -> build_columns(bucket, assigns)
      end

    _ ->
      []
  end
end
```

**Correct:**

```elixir
@spec get_current_columns(map()) :: list()
def get_current_columns(%{alternate_flow: true, selected_bucket: nil}), do: []

def get_current_columns(%{alternate_flow: true} = assigns) do
  build_columns(assigns.selected_bucket, assigns)
end

def get_current_columns(_assigns), do: []
```

---

### EX-02 — Use `cond` for multiple mutually exclusive conditions
**Severity:** low

**Why:** 3+ branches evaluating different conditions over the same data read
better as `cond` than nested `case`/`if-else`, especially when conditions
aren't simple pattern matches.

**Anti-pattern:**

```elixir
if all_matches != [] do
  [hd(all_matches) | other_filters]
else
  if all_bucket do
    [Map.put(all_bucket, :disabled, false) | filtered_filters]
  else
    filtered_filters
  end
end
```

**Correct:**

```elixir
{all_matches, other_filters} =
  Enum.split_with(filtered_filters, &(&1.value == "all"))

all_bucket = Enum.find(all_filters, &(&1.value == "all"))

cond do
  all_matches != [] ->
    [hd(all_matches) | other_filters]

  all_bucket ->
    [Map.put(all_bucket, :disabled, false) | filtered_filters]

  true ->
    filtered_filters
end
```

---

### EX-03 — Group multiple `assign` calls into a single map
**Severity:** low

**Why:** Chained `assign(socket, :key, value)` is verbose. `assign/2`
accepts a full map or keyword list; a keyword list enables filtering nils
with `Enum.reject`.

**Anti-pattern:**

```elixir
socket =
  socket
  |> assign(:is_current_period, Map.get(assigns, :is_current_period, false))
  |> assign(:past_promise, Map.get(assigns, :past_promise))
  |> assign(:show_form, Map.get(assigns, :show_form, false))
```

**Correct:**

```elixir
assigns_to_set = [
  is_current_period: assigns[:is_current_period],
  past_promise: assigns[:past_promise],
  show_form: assigns[:show_form]
]

assigns_filtered = Enum.reject(assigns_to_set, fn {_key, value} -> is_nil(value) end)
socket = assign(socket, assigns_filtered)
```

---

### EX-04 — Extract logic from `handle_event`/`handle_info` into private functions
**Severity:** medium

**Why:** LiveView callbacks orchestrate and delegate; parsing, validation,
and persistence belong in `defp` functions with semantic names — testable
without mounting the LiveView.

**Anti-pattern:**

```elixir
def handle_event("process_csv", %{"csv_content" => csv_content}, socket) do
  country = socket.assigns.selected_country
  rows = String.split(csv_content, "\n")
  # ... 40 lines of parsing, validation, insertion and error handling inline
  {:noreply, socket}
end
```

**Correct:**

```elixir
def handle_event("process_csv", %{"csv_content" => csv_content}, socket) do
  country = socket.assigns.selected_country

  result =
    csv_content
    |> parse_csv_rows()
    |> create_cutoff_periods(country)

  {:noreply, handle_csv_result(socket, result)}
end

defp parse_csv_rows(csv_content), do: ...
defp create_cutoff_periods(rows, country), do: ...
defp handle_csv_result(socket, {:ok, summary}), do: ...
defp handle_csv_result(socket, {:error, errors}), do: ...
```

---

### EX-05 — Avoid `|>` pipe when there is only one transformation
**Severity:** low

**Why:** The pipe pays off when chaining 2+ operations; a single
transformation is more idiomatic as a direct call.

**Anti-pattern:**

```elixir
socket =
  socket
  |> start_async(:get_welcome_kpis, fn -> fetch_welcome_kpis(user_email) end)
```

**Correct:**

```elixir
socket = start_async(socket, :get_welcome_kpis, fn -> fetch_welcome_kpis(user_email) end)
```

---

### EX-06 — Don't duplicate conditions already evaluated in the parent element
**Severity:** medium

**Why:** In HEEx/LiveView, a child under an element with `:if={condition}`
doesn't need to repeat it — duplicated conditions are dead code and future
divergence points.

**Anti-pattern:**

```heex
<div :if={is_recurring?(debt)}>
  <div :if={String.ends_with?(debt.status || "", "_recurring") or
              String.ends_with?(debt.sub_state || "", "_recurring")}
       class="flex flex-row mb-1 p-1 rounded-lg">
    ...
  </div>
</div>
```

**Correct:**

```heex
<div :if={is_recurring?(debt)}>
  <div class="flex flex-row mb-1 p-1 rounded-lg">
    ...
  </div>
</div>
```

---

## Tests

### TS-01 — Use factories instead of hand-built test data
**Severity:** medium · **Convention rule:** n/a if the repo has no factories.

**Why:** Manually building structs/maps in tests couples them to the
schema. ExMachina factories keep test data in sync; every new schema ships
with its factory.

```elixir
# anti-pattern
context_template = %ContextTemplate{id: 1, name: "test", active: true}
# correct
context_template = insert(:context_template)
```

### TS-02 — Keep ExUnit specs when refactoring existing code
**Severity:** high

**Why:** Moving/renaming/refactoring functions must not delete their
specs — the public contract keeps its coverage. A refactor that deletes
tests is a merge blocker.

### TS-03 — Add `@spec` to public functions of new modules
**Severity:** low

**Why:** `@spec` documents the contract, enables Dialyzer, and serves as
inline documentation — the convention in domain/helper modules.

### TS-04 — Clean up temporary resources in tests and production code
**Severity:** high

**Why:** Temp files (uploads, attachments) must be removed explicitly. An
`after` block guarantees no garbage accumulates.

```elixir
def process_attachment(file_path) do
  tmp_path = Path.join(System.tmp_dir!(), "attachment_#{uuid}.pdf")
  File.copy!(file_path, tmp_path)

  try do
    EmailSender.send_email_with_attachment(tmp_path)
  after
    File.rm(tmp_path)
  end
end
```

### TS-05 — Extract complex logic into testable functions
**Severity:** medium

**Why:** A `case` block with repo calls, logging, and side effects inside
`handle_event` is hard to unit-test. Extract a `defp` with clear
inputs/outputs; test it without mounting the LiveView.

```elixir
def handle_event("send_email", params, socket) do
  case send_and_track_email(params, socket.assigns) do
    {:ok, email} -> {:noreply, assign(socket, :sent_email, email)}
    {:error, reason} -> {:noreply, put_flash(socket, :error, reason)}
  end
end

defp send_and_track_email(params, assigns) do
  with {:ok, {:ok, %{email: email}}} <- EmailSender.send_email(build_params(params, assigns)),
       {:ok, _} <- EmailManager.update_with_message_id(assigns.saved_email_id, email.message_id) do
    {:ok, email}
  end
end
```

---

## Error Handling / Nil Safety

### ERR-01 — Don't assign to the socket after an `if` check that doesn't early-return
**Severity:** high

**Why:** `if value do log ... end` that doesn't stop execution is dead
code — the nil flows through into the next `assign`.

**Anti-pattern:**

```elixir
thread = EmailManager.get_thread_with_emails(thread_id)

if thread do
  Logger.debug("Thread found: #{thread.id}")
else
  Logger.error("Thread not found for ID: #{thread_id}")
  # No early return
end

# thread can be nil here!
socket |> assign(:selected_thread, thread)
```

**Correct:**

```elixir
case EmailManager.get_thread_with_emails(thread_id) do
  nil ->
    Logger.error("Thread not found for ID: #{thread_id}")
    {:noreply, socket}

  thread ->
    Logger.debug("Thread found: #{thread.id}")
    {:noreply, assign(socket, :selected_thread, thread)}
end
```

---

### ERR-02 — Use `Enum.find` with pattern match instead of conditional list logic
**Severity:** medium

**Why:** `Enum.filter` + take-first is more code than needed; `Enum.find`
handles the nil case naturally.

**Anti-pattern:**

```elixir
related_active = Enum.filter(related, fn item -> item.status != "deprecated" end)
account = if related_active != [], do: hd(related_active), else: nil
result = if account, do: %{data | account: account}, else: data
```

**Correct:**

```elixir
case Enum.find(related, fn %{status: status} -> status != "deprecated" end) do
  nil -> data
  account -> %{data | account: account}
end
```

---

### ERR-03 — Use idiomatic map key access instead of conditionals
**Severity:** low

**Why:** `map[:key]` is safe access (nil if missing); pattern matching with
a catch-all is explicit. `if is_map(x), do: x.field` is not idiomatic.

```elixir
# anti-pattern
country = if is_map(cr), do: cr.country, else: nil
# correct
country = cr[:country]
# or
case cr do
  %{country: country} -> country
  _ -> nil
end
```

---

### ERR-04 — Handle `Repo.get/2` nil with `with` or `case`
**Severity:** high

**Why:** `Repo.get` returns `nil` when missing — NEVER `{:error,
changeset}`. A `case` branch matching `{:error, changeset}` is
unreachable dead code.

**Anti-pattern:**

```elixir
case Repo.get(Account, account_id) do
  nil -> {:error, :not_found}
  {:error, changeset} -> {:error, changeset}  # This branch NEVER executes
  account -> account |> Account.changeset(attrs) |> Repo.update()
end
```

**Correct:**

```elixir
with %Account{} = account <- Repo.get(Account, account_id) do
  account
  |> Account.changeset(attrs)
  |> Repo.update()
end
```

---

### ERR-05 — Access assigns with `get_in` instead of `&&` chains
**Severity:** low

**Why:** Chained `&&` over nested keys is a JS pattern; `get_in` on a map
returns nil if any key is missing.

```heex
<!-- anti-pattern -->
<div :if={Map.get(assigns, :right_drawer_items) &&
           Map.get(assigns.right_drawer_items, :modules, []) != []}>
<!-- correct -->
<div :if={get_in(assigns, [:right_drawer_items, :modules]) != []}>
```

---

### ERR-06 — Keep `case` over `{:error, %Ecto.Changeset{}}` inside transactions
**Severity:** high

**Why:** Wrapped in `Repo.transaction`, a bare `{:error, reason}` else
clause collapses validation changesets into an opaque reason, silently
losing field errors. Inner validation failures must keep the changeset
shape so the transaction's `else` can match it.

```elixir
with {:ok, user} <- create_user(attrs),
     {:ok, team} <- create_team(attrs, user) do
  {:ok, %{user: user, team: team}}
else
  {:error, %Ecto.Changeset{} = changeset} -> {:error, changeset}
end
```

---

## Performance / DB

### PF-01 — Always index foreign keys in migrations
**Severity:** high

**Why:** A `references/2` column without its index makes joins and lookups
full table scans.

```elixir
alter table(:context_templates) do
  add(:active, :boolean, default: true)
  add(:workflow_config_id, references(:workflow_configs, on_delete: :nilify_all))
end

create index(:context_templates, [:workflow_config_id])
```

### PF-02 — Order composite index columns for the real queries
**Severity:** high

**Why:** A composite index is only usable when leading columns match the
query's filter prefix (highest selectivity / always-filtered first).

```elixir
# anti-pattern: queries always filter by entity_type first
create index(:events, [:entity_id, :entity_type, :event_type_id])
# correct: entity_type leads
create index(:events, [:entity_type, :entity_id, :event_type_id])
```

### PF-03 — Don't duplicate external database repos
**Severity:** high

**Why:** A second `Ecto.Repo` on the same external DB doubles the pool,
can exhaust DB limits, and hides the second repo from monitoring. Reuse the
existing repo or move it to the semantically owning app.

### PF-04 — Use `Repo.update_all` with an explicit query instead of get + update
**Severity:** medium

**Why:** get + update issues 2 queries; `update_all` with a `from` is one
`UPDATE ... WHERE`.

```elixir
update_query =
  from(c in "accounts",
    where: c.id == ^account_id,
    update: [set: [status: ^new_status]]
  )

ExternalRepo.update_all(update_query, [])
```

### PF-05 — Batch N+1 lookups into one `WHERE IN` query
**Severity:** high

**Why:** Per-item lookups inside template `:for` comprehensions multiply
queries (8 tags × 50 pages = 250+ queries). Add a batch function returning
a map, pre-load once before rendering.

```elixir
def get_pages_by_slugs(slugs, context_id) do
  from(p in Page, where: p.slug in ^slugs and p.context_id == ^context_id)
  |> Repo.all()
  |> Map.new(&{&1.slug, &1})
end
```

### PF-06 — Deterministic pagination tiebreak
**Severity:** medium

**Why:** Plain `OFFSET` pages drift when rows are inserted/deleted between
pages. Order by a stable unique key so the boundary is deterministic.

```elixir
from(p in Page, order_by: [asc: p.id], offset: ^offset, limit: ^limit)
```

---

## Architecture / Design

### AR-01 — Don't duplicate repos — move them to their semantically owning app
**Severity:** high

**Why:** In an umbrella, each external-DB `Ecto.Repo` lives in the app that
owns it. Two apps needing the same external DB share through the
dependency — never duplicate the repo module.

**Correct:**

```elixir
# Option A: use the owning app's repo if the dependency exists
alias CoreApp.ExternalRepo

# Option B: if the other app is the semantic owner, move the repo there
# and have the first app consume it
```

### AR-02 — Use typed structs in port callbacks instead of generic maps
**Severity:** medium

**Why:** `@callback` with `map()` defeats Dialyzer. Structs with explicit
types document exactly what the port accepts and make contracts verifiable.

```elixir
# anti-pattern — map() defeats Dialyzer
@callback upsert_interaction(attrs :: map()) ::
            {:ok, Interaction.t()} | {:error, Error.t()}
# correct — an explicit struct type documents the port contract
@callback upsert_interaction(Interaction.t()) ::
            {:ok, Interaction.t()} | {:error, Error.t()}
```

### AR-03 — No hardcoded environment URLs — use runtime configuration
**Severity:** medium

**Why:** Hardcoded endpoints prevent per-environment configuration. Use
`config/runtime.exs` with `System.get_env/2` and
`Application.compile_env!/3`.

```elixir
# config/runtime.exs
config :my_app_web, :onboarding_url,
  System.get_env("ONBOARDING_URL", "https://onboarding.example.com/")

# in the module
@onboarding_url Application.compile_env!(:my_app_web, :onboarding_url)
```

---

## Documentation / i18n

### I18N-01 — Use `gettext` for all user-visible strings in HEEx
**Severity:** medium · **Convention rule:** n/a if the repo has no gettext.

**Why:** Every user-visible string must be wrapped in `gettext(...)`;
hardcoded strings break translation. CI can detect them.

```heex
<!-- anti-pattern -->
<h1 class="text-2xl font-semibold text-gray-900">Recurring payments</h1>
<!-- correct -->
<h1 class="text-2xl font-semibold text-gray-900"><%= gettext("Recurring payments") %></h1>
```

### I18N-02 — Group related configs under the same namespace key
**Severity:** low

**Why:** Scattered config keys hurt readability and autocomplete. Group
related entries under one namespace.

---

## Correctness

### LG-01 — Don't add insecure SSL configuration as the dev default
**Severity:** medium

**Why:** `ssl_opts: [verify: :verify_none]` committed in `config/dev.exs`
makes an insecure setup the default for the whole team. Keep dev config
clean; put sandbox SSL overrides in a local, uncommitted file.

### LG-02 — Implement an expiry strategy in in-memory caches
**Severity:** medium

**Why:** A GenServer cache with no TTL/sweep grows forever; restart-only
cleanup is not a strategy. Store `{value, expires_at}` and sweep on a
timer.

```elixir
@ttl_ms :timer.minutes(30)
@sweep_interval_ms :timer.minutes(5)

def init(state) do
  schedule_sweep()
  {:ok, state}
end

defp schedule_sweep do
  Process.send_after(self(), :sweep, @sweep_interval_ms)
end

def handle_info(:sweep, state) do
  now = System.monotonic_time(:millisecond)
  new_state = Map.reject(state, fn {_k, {_v, expires_at}} -> expires_at < now end)
  schedule_sweep()
  {:noreply, new_state}
end
```

---

## Naming / Readability

### NM-01 — Use consistent canonical values in analytics event attributes
**Severity:** medium

**Why:** Dimension values must match the rest of the system's constants,
or dashboards fragment.

```heex
<!-- anti-pattern -->
<div id="panel-switch-tracker" phx-hook="PanelSwitchTracker" data-current-panel={@preset.name}>
<!-- correct -->
<div id="panel-switch-tracker" phx-hook="PanelSwitchTracker"
     data-current-panel="active_portfolio"
     data-preset-name={@preset && @preset.name}>
```

---

## Automation — most frequent patterns and the tools that catch them

| # | Pattern | Rule IDs | Tool |
|---|---------|----------|------|
| 1 | Nested `case` / deep `if-else` | EX-01, EX-02 | **Credo** — `CondStatements`, `CyclomaticComplexity` |
| 2 | Chained `assign/3` calls | EX-03 | **Credo** — custom check counting pipes into `assign` |
| 3 | Hardcoded strings without `gettext` | I18N-01 | `mix gettext.extract` + CI check for untranslated strings |
| 4 | FK without index in migrations | PF-01 | `mix ecto.migrations` + custom linter (every `references/2` has its `create index`) |
| 5 | Hardcoded URLs in source | AR-03 | **Credo** — custom check matching `https?://` literals |
| 6 | Single-transform `\|>` pipe | EX-05 | **Credo** — `PipeChainStart` |
| 7 | `Repo.get` without nil handling | ERR-04 | **Dialyzer** / custom linter detecting `Repo.get` without pattern-match |

## Pitfalls

- **Read the code before citing a rule** — a finding needs a real
  file:line, never a paraphrase of someone else's summary.
- **Convention-dependent rules** — TS-01/I18N-01 apply only when the repo
  uses the library; otherwise mark n/a.
- **Don't apply low-severity rules as merge blockers** — keep severity
  honest; nitpicking erodes review trust.
- **Adjust for repo shape** — the catalog assumes idiomatic LiveView/
  Phoenix; adapt for GenServer apps, umbrella boundaries (PF-03/AR-01),
  and repos without gettext.