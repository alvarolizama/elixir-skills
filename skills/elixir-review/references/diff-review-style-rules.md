# Diff Review Rules — Elixir Style & Idioms (EX)

Part 1 of 3 of the diff-review rulebook for Elixir/Phoenix codebases
(LiveView + Ecto + gettext + ExMachina). Every rule has a **severity**, a
**why**, an **anti-pattern**, and the **correct form**. Rule IDs are stable
across the whole rulebook — cite them in review comments (`EX-01: use
multiple clauses instead of nested case`).

Severity legend:

- **high** — merge blocker: bugs, leaks, broken contracts, data-loss risk.
- **medium** — should fix: readability, testability, idiomatic Elixir.
- **low** — nit: optional polish, style preference.

Companion rule families: `diff-review-correctness-rules.md`
(TS/ERR) and `diff-review-system-rules.md` (PF/AR/I18N/LG/NM, automation
table, pitfalls).

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
