# Elixir/Phoenix Code Review Rules — Full Catalog

Distilled from thousands of code-review comments across a large production
Elixir/Phoenix umbrella (LiveView + Ecto + gettext + ExMachina). Every rule
has a **severity**, a **why**, an **anti-pattern**, and the **correct form**.
Rule IDs are stable — cite them in review comments (e.g. "EX-01: use multiple
clauses instead of nested case").

Severity legend:

- **high** — merge blocker: bugs, leaks, broken contracts, data loss risk.
- **medium** — should fix: readability, testability, idiomatic Elixir.
- **low** — nit: optional polish, style preference.

---

## Elixir Style / Idioms

### EX-01 — Prefer pattern matching with multiple clauses over nested `case`
**Severity:** medium

**Why:** When conditions in a `case` include specific values like `nil` or
boolean flags, multiple function clauses are more idiomatic. They reduce
indentation, enable early return, and make the happy path read linearly.

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
  selected_bucket = assigns.selected_bucket
  build_columns(selected_bucket, assigns)
end

def get_current_columns(_assigns), do: []
```

---

### EX-02 — Use `cond` for multiple mutually exclusive conditions
**Severity:** low

**Why:** With 3+ branches evaluating different conditions over the same data,
`cond` reads better than nested `case` or `if/else` chains — especially when
the conditions are not simple pattern matches.

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

**Why:** Chaining multiple `assign(socket, :key, value)` calls is needlessly
verbose. `assign/2` accepts a full map or keyword list. A keyword list also
enables filtering nils with `Enum.reject`.

**Anti-pattern:**

```elixir
socket =
  socket
  |> assign(:is_current_period, Map.get(assigns, :is_current_period, Map.get(socket.assigns, :is_current_period, false)))
  |> assign(:past_promise, Map.get(assigns, :past_promise, Map.get(socket.assigns, :past_promise)))
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

**Why:** LiveView callbacks should orchestrate and delegate, not concentrate
parsing, validation, and persistence. A long callback with inline `case`
blocks is hard to read and test. Team convention: `defp` functions with
semantic names.

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

**Why:** The pipe operator adds readability when chaining 2+ operations. For
a single transformation, the direct call is more idiomatic and less visual
noise.

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

**Why:** In HEEx/LiveView, if a parent element already has `:if={condition}`,
children don't need to repeat it. Duplicated conditions create dead code and
future divergence points.

**Anti-pattern:**

```heex
<div :if={is_structured_payment?(debt)}>
  <div :if={String.ends_with?(debt.status || "", "_structured_payment") or
              String.ends_with?(debt.sub_state || "", "_structured_payment")}
       class="flex flex-row mb-1 p-1 rounded-lg">
    ...
  </div>
</div>
```

**Correct:**

```heex
<div :if={is_structured_payment?(debt)}>
  <div class="flex flex-row mb-1 p-1 rounded-lg">
    ...
  </div>
</div>
```

---

## Tests

### TS-01 — Use factories instead of hand-built test data
**Severity:** medium

**Why:** Manually building structs/maps in tests creates fragile coupling to
the schema. Use ExMachina factories to keep test data in sync with the
schema. Every new schema ships with its factory.

**Anti-pattern:**

```elixir
test "creates workflow config" do
  context_template = %ContextTemplate{id: 1, name: "test", active: true}
  # ... build data by hand
end
```

**Correct:**

```elixir
test "creates workflow config" do
  context_template = insert(:context_template)
  # ... use the factory
end
```

---

### TS-02 — Keep ExUnit specs when refactoring existing code
**Severity:** high

**Why:** When moving, renaming, or refactoring functions, existing tests must
be updated accordingly. Never delete specs because the code changed — the
public contract keeps its coverage.

**Anti-pattern:**

```
# parse_filters/1 specs were deleted during the refactor
# The module now has no tests
```

**Correct:**

```elixir
describe "parse_filters/1" do
  test "returns empty list when no filters" do
    assert [] == RadioButtonFilterResolver.parse_filters(%{})
  end

  test "returns correct columns for alternate flow" do
    assigns = %{alternate_flow: true, selected_bucket: nil}
    assert [] == RadioButtonFilterResolver.get_current_columns(assigns)
  end
end
```

---

### TS-03 — Add `@spec` to public functions of new modules
**Severity:** low

**Why:** New modules — especially helpers and managers — should carry `@spec`
on public functions. It documents the contract, enables Dialyzer, and serves
as inline documentation. `@spec` + `@doc` is the convention in domain modules.

**Anti-pattern:**

```elixir
defmodule MyAppWeb.Helpers.RadioButtonFilterResolver do
  def get_current_columns(assigns) do
    # no @spec
  end
end
```

**Correct:**

```elixir
defmodule MyAppWeb.Helpers.RadioButtonFilterResolver do
  @spec get_current_columns(map()) :: list()
  def get_current_columns(%{alternate_flow: true, selected_bucket: nil}), do: []

  @spec get_current_columns(map()) :: list()
  def get_current_columns(%{alternate_flow: true} = assigns) do
    ...
  end
end
```

---

### TS-04 — Clean up temporary resources in tests and production code
**Severity:** high

**Why:** Temporary files created during processing (uploads, attachments) must
be removed explicitly. A `File.rm` after use, or an `after` block, guarantees
pods don't accumulate garbage.

**Anti-pattern:**

```elixir
def process_attachment(file_path) do
  tmp_path = Path.join(System.tmp_dir!(), "attachment_#{uuid}.pdf")
  File.copy!(file_path, tmp_path)
  EmailSender.send_email_with_attachment(tmp_path)
  # tmp_path is never removed
end
```

**Correct:**

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

---

### TS-05 — Extract complex logic into testable functions
**Severity:** medium

**Why:** A `case` block with multiple repo calls, logging, and side effects
inside `handle_event` is hard to unit-test. Extracting the logic into a
`defp` with clear inputs/outputs lets you test it without mounting the full
LiveView.

**Anti-pattern:**

```elixir
def handle_event("send_email", params, socket) do
  # 30+ lines: validate, build params, call repo, log, handle errors...
  case EmailSender.send_email(email_params) do
    {:ok, {:ok, %{email: email}}} ->
      case EmailTracker.update_with_message_id(saved_email_id, email.message_id) do
        {:ok, _} -> ...
        {:error, err} -> ...
      end

    {:error, error} ->
      Logger.error("...")
  end
end
```

**Correct:**

```elixir
def handle_event("send_email", params, socket) do
  case send_and_track_email(params, socket.assigns) do
    {:ok, email} -> {:noreply, assign(socket, :sent_email, email)}
    {:error, reason} -> {:noreply, put_flash(socket, :error, reason)}
  end
end

defp send_and_track_email(params, assigns) do
  with {:ok, {:ok, %{email: email}}} <- EmailSender.send_email(build_params(params, assigns)),
       {:ok, _} <- EmailTracker.update_with_message_id(assigns.saved_email_id, email.message_id) do
    {:ok, email}
  end
end
```

---

## Error Handling / Nil Safety

### ERR-01 — Don't assign to the socket after an `if` check that doesn't early-return
**Severity:** high

**Why:** Checking a value for nil with an `if` only to log, then continuing
and assigning that value to the socket anyway, is dead code that gives false
safety. If the check doesn't stop execution, the nil flows through.

**Anti-pattern:**

```elixir
thread = EmailTracker.get_thread_with_emails(thread_id)

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
case EmailTracker.get_thread_with_emails(thread_id) do
  nil ->
    Logger.error("Thread not found for ID: #{thread_id}")
    {:noreply, socket}

  thread ->
    Logger.debug("Thread found: #{thread.id}")
    {:noreply, assign(socket, :selected_thread, thread)}
end
```

---

### ERR-02 — Use `Enum.find` with pattern match instead of conditional logic over lists
**Severity:** medium

**Why:** `Enum.filter` + take-first is more code than needed. `Enum.find` with
a pattern match is more expressive and handles the nil case naturally.

**Anti-pattern:**

```elixir
related_active = Enum.filter(related, fn item -> item.status != "deprecated" end)
credit_repair = if related_active != [], do: hd(related_active), else: nil
result = if credit_repair, do: %{data | credit_repair: credit_repair}, else: data
```

**Correct:**

```elixir
case Enum.find(related, fn %{status: status} -> status != "deprecated" end) do
  nil -> data
  credit_repair -> %{data | credit_repair: credit_repair}
end
```

---

### ERR-03 — Use idiomatic map key access instead of conditionals
**Severity:** low

**Why:** For accessing a field of a map that may be nil, use `map[:key]`
(safe access, returns nil if the key is missing) or pattern matching with a
catch-all clause. `if is_map(x), do: x.field, else: nil` is not idiomatic.

**Anti-pattern:**

```elixir
country = if is_map(cr), do: cr.country, else: nil
```

**Correct:**

```elixir
# Option 1: safe access (returns nil if the key is missing)
country = cr[:country]

# Option 2: explicit pattern matching
country =
  case cr do
    %{country: country} -> country
    _ -> nil
  end
```

---

### ERR-04 — Handle `Repo.get/2` nil with `with` or `case`
**Severity:** high

**Why:** `Repo.get` returns `nil` when the record doesn't exist — never
`{:error, changeset}`. Use `with %Schema{} = record <- Repo.get(...)`: if the
result is nil, the `with` fails and returns nil automatically.

**Anti-pattern:**

```elixir
def update_credit_repair(credit_repair_id, attrs) do
  case Repo.get(CreditRepair, credit_repair_id) do
    nil -> {:error, :not_found}
    {:error, changeset} -> {:error, changeset}  # This branch NEVER executes
    credit_repair -> credit_repair |> CreditRepair.changeset(attrs) |> Repo.update()
  end
end
```

**Correct:**

```elixir
def update_credit_repair(credit_repair_id, attrs) do
  with %CreditRepair{} = credit_repair <- Repo.get(CreditRepair, credit_repair_id) do
    credit_repair
    |> CreditRepair.changeset(attrs)
    |> Repo.update()
  end
end
```

---

### ERR-05 — Access assigns with `get_in` instead of `&&` chains
**Severity:** low

**Why:** Checking nested keys in `assigns` with chained `&&` is a JavaScript
pattern. In Elixir, `get_in` on a map returns nil automatically if any key is
missing — safer and more concise.

**Anti-pattern:**

```heex
<div :if={Map.get(assigns, :right_drawer_items) &&
           Map.get(assigns.right_drawer_items, :modules, []) != []}>
```

**Correct:**

```heex
<div :if={get_in(assigns, [:right_drawer_items, :modules]) != []}>
```

---

## Performance / DB

### PF-01 — Always index foreign keys in migrations
**Severity:** high

**Why:** When adding a `references/2` column in an Ecto migration, create the
corresponding index in the same migration. Without it, joins and lookups on
that FK do full table scans.

**Anti-pattern:**

```elixir
alter table(:context_templates) do
  add(:active, :boolean, default: true)
  add(:workflow_config_id, references(:workflow_configs, on_delete: :nilify_all))
end
# No create index
```

**Correct:**

```elixir
alter table(:context_templates) do
  add(:active, :boolean, default: true)
  add(:workflow_config_id, references(:workflow_configs, on_delete: :nilify_all))
end

create index(:context_templates, [:workflow_config_id])
```

---

### PF-02 — Order composite index columns for the real queries
**Severity:** high

**Why:** Column order in a composite index matters. The index must start with
the column used as the prefix in real queries (highest selectivity /
always-filtered). A wrongly ordered index may never be used by the query
planner.

**Anti-pattern:**

```elixir
# Index created as (entity_id, entity_type, event_type_id)
# but queries always filter by entity_type first
create index(:events, [:entity_id, :entity_type, :event_type_id])
```

**Correct:**

```elixir
# entity_type goes first because queries without entity_type don't make sense
create index(:events, [:entity_type, :entity_id])
# If event_type_id is needed for performance, append it at the end
create index(:events, [:entity_type, :entity_id, :event_type_id])
```

---

### PF-03 — Don't duplicate external database repos
**Severity:** high

**Why:** A second `Ecto.Repo` pointing at the same external database doubles
the connection pool, can exhaust the DB's limits, and hides the second repo
from monitoring. Reuse the existing repo or move it to the owning app.

**Anti-pattern:**

```elixir
# PeopleApp.ExternalRepo already exists with pool_size: 10
# Creating a new one in InteractionsApp:
defmodule InteractionsApp.ExternalRepo do
  use Ecto.Repo,
    otp_app: :interactions_app,
    adapter: Ecto.Adapters.Postgres
  # pool_size: 10 → now 20 connections to the external DB
end
```

**Correct:**

```elixir
# Reuse the existing repo, or if InteractionsApp needs it,
# move the repo to a shared app and update the dependency
alias PeopleApp.ExternalRepo
```

---

### PF-04 — Use `Repo.update_all` with an explicit query instead of get + update
**Severity:** medium

**Why:** The `Repo.get` + `Repo.update` pattern issues 2 queries.
`Repo.update_all` with a `from` is a single `UPDATE ... WHERE` — the
idiomatic pattern for simple field updates.

**Anti-pattern:**

```elixir
credit_repair = ExternalRepo.get!(CreditRepair, credit_repair_id)
ExternalRepo.update!(Ecto.Changeset.change(credit_repair, status: new_status))
```

**Correct:**

```elixir
update_query =
  from(c in "credit_repairs",
    where: c.id == ^credit_repair_id,
    update: [set: [status: ^new_status]]
  )

ExternalRepo.update_all(update_query, [])
```

---

## Architecture / Design

### AR-01 — Don't duplicate repos — move them to their semantically owning app
**Severity:** high

**Why:** In an umbrella, each external-DB `Ecto.Repo` lives in the app that
owns it semantically. If two apps need the same external DB, share the repo
through the dependency — don't duplicate it.

**Anti-pattern:**

```elixir
# PeopleApp.ExternalRepo already exists
# InteractionsApp creates its own:
defmodule InteractionsApp.ExternalRepo do
  use Ecto.Repo, otp_app: :interactions_app, adapter: Ecto.Adapters.Postgres
end
```

**Correct:**

```elixir
# Option A: use PeopleApp.ExternalRepo directly if the dependency exists
alias PeopleApp.ExternalRepo

# Option B: if InteractionsApp is the semantic owner, move the repo there
# and have PeopleApp consume it
```

---

### AR-02 — Use typed structs in port callbacks instead of generic maps
**Severity:** medium

**Why:** `@behaviour` ports should use structs with explicit types in their
`@callback`, not generic `map()`. This lets Dialyzer verify contracts and
documents exactly what data structure the port accepts.

**Anti-pattern:**

```elixir
defmodule Core.Ports.Outbound.Assignments.LastInteractionsRepositoryPort do
  @callback upsert_interaction(attrs :: map()) ::
              {:ok, LastInteraction.t()} | {:error, Error.t()}
end
```

**Correct:**

```elixir
defmodule Core.Ports.Outbound.Assignments.LastInteractionsRepositoryPort do
  @callback upsert_interaction(
              EmailInteraction.t()
              | WhatsappInteraction.t()
              | CallInteraction.t()
            ) :: {:ok, LastInteraction.t()} | {:error, Error.t()}
end
```

---

### AR-03 — No hardcoded environment URLs — use runtime configuration
**Severity:** medium

**Why:** Hardcoded URLs in source (external service endpoints, staging URLs)
prevent proper per-environment configuration. Use
`Application.compile_env!/3` over `config/runtime.exs` with
`System.get_env/2`.

**Anti-pattern:**

```elixir
defmodule MyAppWeb.Shared.Sidebar.TopBar do
  @onboarding_url "https://onboarding.example.com/"

  def render_onboarding_link(assigns) do
    ~H"<a href={@onboarding_url}>Onboarding</a>"
  end
end
```

**Correct:**

```elixir
# config/runtime.exs
config :my_app_web, :onboarding_url,
  System.get_env("ONBOARDING_URL", "https://onboarding.example.com/")

# In the module:
@onboarding_url Application.compile_env!(:my_app_web, :onboarding_url)
```

---

## Documentation / i18n

### I18N-01 — Use `gettext` for all user-visible strings in HEEx
**Severity:** medium

**Why:** Every string rendered to the user in HEEx templates must be wrapped
in `gettext(...)`. Hardcoded strings break internationalization and make the
UI untranslatable. CI can detect hardcoded strings.

**Anti-pattern:**

```heex
<h1 class="text-2xl font-semibold text-gray-900">
  Structured payments
</h1>
```

**Correct:**

```heex
<h1 class="text-2xl font-semibold text-gray-900">
  <%= gettext("Structured payments") %>
</h1>
```

---

### I18N-02 — Group related configs under the same namespace key
**Severity:** low

**Why:** When adding entries to `config.exs`, group related ones under a
single namespace instead of scattered keys. Improves readability and
autocomplete in consuming code.

**Anti-pattern:**

```elixir
config :core, :assignments_repository, Core.Adapters.Outbound.Assignments.AssignmentsRepository

config :core, :assignments_repositories,
  priority_rules: Core.Adapters.Outbound.Assignments.AssignmentPriorityRulesRepository
```

**Correct:**

```elixir
config :core, :assignments_repositories,
  assignments: Core.Adapters.Outbound.Assignments.AssignmentsRepository,
  priority_rules: Core.Adapters.Outbound.Assignments.AssignmentPriorityRulesRepository
```

---

## Correctness

### LG-01 — Don't add insecure SSL configuration as the dev default
**Severity:** medium

**Why:** Enabling SSL with `verify: :verify_none` in `config/dev.exs` makes an
insecure setup the default for the whole team. If a developer needs a remote
environment, it should be a local, uncommitted config file.

**Anti-pattern:**

```elixir
# config/dev.exs
config :products, ProductsApp.BankRepo,
  url: System.get_env("BANK_POSTGRES_URL"),
  ssl: true,
  ssl_opts: [verify: :verify_none]  # Hardcoded for everyone
```

**Correct:**

```elixir
# config/dev.exs — only what local development needs
config :products, ProductsApp.BankRepo,
  url: System.get_env("BANK_POSTGRES_URL")

# If someone needs SSL for a sandbox connection:
# add it in dev.local.exs (not committed)
```

---

### LG-02 — Implement an expiry strategy in in-memory caches
**Severity:** medium

**Why:** A cache module with no TTL or sweep mechanism accumulates forever.
If the only cleanup mechanism is a pod restart, the cache can grow without
bounds. Document the expiry behavior or implement a periodic sweep.

**Anti-pattern:**

```elixir
defmodule ProductsApp.StructuredPayments.Cache do
  use GenServer

  def get(key), do: GenServer.call(__MODULE__, {:get, key})
  def put(key, value), do: GenServer.cast(__MODULE__, {:put, key, value})
  # No expiry, no sweep, no size limit
end
```

**Correct:**

```elixir
defmodule ProductsApp.StructuredPayments.Cache do
  use GenServer

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
end
```

---

## Naming / Readability

### NM-01 — Use consistent canonical values in analytics event attributes
**Severity:** medium

**Why:** When instrumenting analytics events, dimension values must be
consistent with the rest of the system. Using a dynamic value where the rest
of the system uses constants produces inconsistent dashboards.

**Anti-pattern:**

```heex
<div
  id="panel-switch-tracker"
  phx-hook="PanelSwitchTracker"
  data-current-panel={@preset.name}
>
```

**Correct:**

```heex
<div
  id="panel-switch-tracker"
  phx-hook="PanelSwitchTracker"
  data-current-panel="active_portfolio"
  data-preset-name={@preset && @preset.name}
>
```

---

## Automation — most frequent patterns and the tools that catch them

| # | Pattern | Rule IDs | Tool |
|---|---------|----------|------|
| 1 | Nested `case` / deep `if-else` | EX-01, EX-02 | **Credo** — `Credo.Check.Refactor.CondStatements`, `Credo.Check.Refactor.CyclomaticComplexity` |
| 2 | Chained `assign/3` calls | EX-03 | **Credo** — custom check counting pipes into `assign` |
| 3 | Hardcoded strings without `gettext` | I18N-01 | `mix gettext.extract` + CI check for untranslated strings |
| 4 | FK without index in migrations | PF-01 | `mix ecto.migrations` + custom linter verifying every `references/2` has its `create index` |
| 5 | Hardcoded URLs in source | AR-03 | **Credo** — custom check matching `https?://` literals |
| 6 | One-line `def` with a long body | — | **Credo** — `Credo.Check.Readability.SingleFunctionToBlockPipe` |
| 7 | `|>` pipe for a single transformation | EX-05 | **Credo** — `Credo.Check.Refactor.PipeChainStart` |
| 8 | `Repo.get` without nil handling | ERR-04 | **Dialyzer** (type analysis) or a custom linter detecting `Repo.get` without pattern-match on the result |
