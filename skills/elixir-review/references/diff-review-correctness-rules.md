# Diff Review Rules — Tests & Nil Safety (TS, ERR)

Part 2 of 3 of the diff-review rulebook for Elixir/Phoenix codebases
(LiveView + Ecto + gettext + ExMachina). Every rule has a **severity**, a
**why**, an **anti-pattern**, and the **correct form**. Rule IDs are stable
across the whole rulebook — cite them in review comments (`ERR-04:
Repo.get/2 returns nil, never {:error, changeset}`).

Severity legend:

- **high** — merge blocker: bugs, leaks, broken contracts, data-loss risk.
- **medium** — should fix: readability, testability, idiomatic Elixir.
- **low** — nit: optional polish, style preference.

Companion rule families: `diff-review-style-rules.md` (EX) and
`diff-review-system-rules.md` (PF/AR/I18N/LG/NM, automation table,
pitfalls).

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

### ERR-05 — Access assigns with `get_in` instead of `&&` chains — then MATCH on the list
**Severity:** low

**Why:** Chained `&&` over nested keys is a JS pattern; `get_in` on a map
returns nil if any key is missing. But `get_in(...) != []` is nil-UNSAFE:
when the assign is missing, `get_in` returns `nil`, `nil != []` is true,
and the element renders when it should not. Match on the non-empty list
shape instead.

```heex
<!-- anti-pattern -->
<div :if={Map.get(assigns, :right_drawer_items) &&
           Map.get(assigns.right_drawer_items, :modules, []) != []}>
<!-- still wrong: nil != [] is true when the assign is missing -->
<div :if={get_in(assigns, [:right_drawer_items, :modules]) != []}>
<!-- correct: renders only for an actual non-empty list -->
<div :if={match?([_ | _], get_in(assigns, [:right_drawer_items, :modules]))}>
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
