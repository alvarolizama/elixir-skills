---
name: phoenix-wizard-forms
description: "Build step-by-step wizard and tabbed configuration forms in Phoenix LiveView using section-scoped Ecto changesets and a single Edit LiveView."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [elixir, phoenix, liveview, forms, wizard, tabs, ecto]
    related_skills: [software-development/phoenix-umbrella-project-setup, software-development/test-driven-development]
---

# Phoenix Wizard & Tabbed Forms

Use this skill when a user wants a complex Phoenix form split into either:

- a **step-by-step wizard** (one section per step, continues automatically), or
- a **tabbed edit page** (each section is a tab and saves independently).

Both UX patterns can share one `Edit` LiveView and one schema if you break the
changeset into section-scoped changesets.

## Common triggers

- "Create X step by step: first name, then API, then models..."
- "I want tabs when editing: API, Models, Soul, Limits"
- A form has many unrelated fields that overwhelm the user on one page
- Some fields (API URL, key, models) only make sense as a group

## Data model approach

1. Make the optional fields nullable in the database so you can create a bare
   skeleton record from step 1.
2. Add an `ALTER TABLE` migration rather than modifying an already-run migration.
3. Keep one schema module; add one changeset function per section plus a
   dispatcher.

## Schema section changesets

```elixir
defmodule MyApp.Foo.FooItem do
  use Ecto.Schema
  import Ecto.Changeset

  @sections [:name, :api, :models, :soul, :limits]

  schema "foo_items" do
    field :title, :string
    field :api_url, :string
    field :api_key, :string
    field :text_model, :string
    field :soul, :string, default: ""
    # ... other fields
  end

  def name_changeset(item, attrs) do
    cast(item, attrs, [:title]) |> validate_required([:title])
  end

  def api_changeset(item, attrs) do
    cast(item, attrs, [:api_url, :api_key])
    |> validate_required([:api_url, :api_key])
  end

  def models_changeset(item, attrs) do
    cast(item, attrs, [:text_model, :embedding_model, :vision_model, :stt_model])
    |> validate_required([:text_model])
  end

  def soul_changeset(item, attrs), do: cast(item, attrs, [:soul])

  def limits_changeset(item, attrs) do
    cast(item, attrs, [:max_steps, :max_retries])
    |> validate_number(:max_steps, greater_than: 0)
    |> validate_number(:max_retries, greater_than: 0, less_than_or_equal_to: 10)
  end

  def section_changeset(item, section, attrs) when section in @sections do
    apply(__MODULE__, :"#{section}_changeset", [item, attrs])
  end

  def sections, do: @sections
end
```

## Context functions

Add a "create skeleton" function and a section-scoped update:

```elixir
def create_foo_with_name(attrs) do
  %FooItem{}
  |> FooItem.name_changeset(attrs)
  |> Repo.insert()
end

def update_foo_section(%FooItem{} = item, section, attrs) do
  # Preserve API key when the user leaves the password input untouched.
  attrs =
    if is_map_key(attrs, "api_key") and attrs["api_key"] == "" do
      Map.delete(attrs, "api_key")
    else
      attrs
    end

  item
  |> FooItem.section_changeset(section, attrs)
  |> Repo.update()
end

def change_foo_section(%FooItem{} = item, section, attrs \\ %{}) do
  FooItem.section_changeset(item, section, attrs)
end
```

## LiveView with tabs + wizard in one file

```elixir
defmodule MyAppWeb.FooLive.Edit do
  use MyAppWeb, :live_view

  alias MyApp.Foo

  @tabs [
    %{id: :name, label: "Profile"},
    %{id: :api, label: "API"},
    %{id: :models, label: "Models"},
    %{id: :soul, label: "Soul"},
    %{id: :limits, label: "Limits"}
  ]

  @tab_order Enum.map(@tabs, & &1.id)

  @impl true
  def handle_params(%{"id" => id} = params, _url, socket) do
    item = Foo.get_foo!(id)
    tab = parse_tab(params["tab"])
    wizard? = params["wizard"] == "1"

    {:noreply,
     socket
     |> assign(:item, item)
     |> assign(:tab, tab)
     |> assign(:wizard?, wizard?)
     |> assign(:tabs, @tabs)
     |> assign_form(tab)}
  end

  @impl true
  def handle_event("switch-tab", %{"tab" => tab}, socket) do
    tab = parse_tab(tab)

    {:noreply,
     socket
     |> assign(:tab, tab)
     |> assign_form(tab)
     |> push_patch(to: build_url(socket.assigns.item, tab, socket.assigns.wizard?))}
  end

  @impl true
  def handle_event("validate", %{"foo" => params}, socket) do
    changeset = Foo.change_foo_section(socket.assigns.item, socket.assigns.tab, params)
    {:noreply, assign(socket, form: to_form(changeset, action: :validate))}
  end

  @impl true
  def handle_event("save", %{"foo" => params}, socket) do
    tab = socket.assigns.tab

    case Foo.update_foo_section(socket.assigns.item, tab, params) do
      {:ok, item} ->
        socket = assign(socket, :item, item)

        if socket.assigns.wizard? do
          case next_tab(tab) do
            nil ->
              {:noreply, push_navigate(socket, to: ~p"/foos/#{item}")}

            next_tab ->
              {:noreply,
               socket
               |> assign(:tab, next_tab)
               |> assign_form(next_tab)
               |> push_patch(to: build_url(item, next_tab, true))}
          end
        else
          {:noreply,
           socket
           |> assign_form(tab)
           |> put_flash(:info, "#{human_tab(tab)} updated")}
        end

      {:error, changeset} ->
        {:noreply, assign(socket, form: to_form(changeset))}
    end
  end

  defp assign_form(socket, tab) do
    assign(socket, form: to_form(Foo.change_foo_section(socket.assigns.item, tab)))
  end

  defp parse_tab(tab) when tab in ["name", "api", "models", "soul", "limits"], do: String.to_existing_atom(tab)
  defp parse_tab(_), do: :name

  defp build_url(item, tab, true), do: ~p"/foos/#{item}/edit?tab=#{tab}&wizard=1"
  defp build_url(item, tab, false), do: ~p"/foos/#{item}/edit?tab=#{tab}"

  defp next_tab(tab) do
    case Enum.drop_while(@tab_order, &(&1 != tab)) do
      [^tab, next | _] -> next
      _ -> nil
    end
  end

  defp human_tab(:name), do: "Profile"
  defp human_tab(:api), do: "API"
  defp human_tab(:models), do: "Models"
  defp human_tab(:soul), do: "Soul"
  defp human_tab(:limits), do: "Limits"
end
```

## Template shape

```heex
<div class="tabs tabs-border" role="tablist">
  <button
    :for={tab <- @tabs}
    type="button"
    role="tab"
    phx-click="switch-tab"
    phx-value-tab={tab.id}
    class={["tab", @tab == tab.id && "tab-active"]}
  >
    {tab.label}
  </button>
</div>

<.form for={@form} id="foo-form" phx-change="validate" phx-submit="save" class="mt-6 space-y-4">
  <div :if={@tab == :name} class="space-y-4">
    <.input field={@form[:title]} label="Name" />
  </div>

  <div :if={@tab == :api} class="space-y-4">
    <.input field={@form[:api_url]} label="API URL" />
    <.input field={@form[:api_key]} type="password" label="API Key" />
  </div>

  <div :if={@tab == :models} class="space-y-4">
    <.input field={@form[:text_model]} label="Text Model" />
  </div>

  <div :if={@tab == :soul} class="space-y-4">
    <.input field={@form[:soul]} type="textarea" label="Soul" rows="10" />
  </div>

  <div :if={@tab == :limits} class="grid grid-cols-2 gap-4">
    <.input field={@form[:max_steps]} type="number" label="Max Steps" />
    <.input field={@form[:max_retries]} type="number" label="Max Retries" />
  </div>

  <div class="pt-2 flex items-center justify-between">
    <button :if={!@wizard?} type="submit" class="btn btn-primary">Save changes</button>
    <div :if={@wizard?} class="flex items-center gap-3">
      <span class="text-sm text-base-content/60">Step ...</span>
      <button type="submit" class="btn btn-primary">
        Continue
        <.icon name="hero-arrow-right" class="ml-1 size-4" />
      </button>
    </div>
  </div>
</.form>
```

## New page

The creation page should only collect the minimum needed to create the record,
then redirect straight into the wizard:

```elixir
def handle_event("save", %{"foo" => params}, socket) do
  case Foo.create_foo_with_name(params) do
    {:ok, item} ->
      {:noreply, push_navigate(socket, to: ~p"/foos/#{item}/edit?tab=api&wizard=1")}

    {:error, changeset} ->
      {:noreply, assign(socket, form: to_form(changeset))}
  end
end
```

## Verification checklist

- `mix ecto.migrate` applies the nullable migration.
- `mix compile --warnings-as-errors` is clean.
- `mix format --check-formatted` passes.
- Tests cover tab switching (`render_click` on the tab button), section updates,
  and wizard redirect after create.

## Common pitfalls

- **Do not expose the saved API key in the edit form.**
  Use a placeholder (e.g. "Leave unchanged to keep current key") and skip the
  field server-side when it arrives as ` ""`.
- **Do not change text, embedding, vision, etc. in a single required bundle.**
  Only the truly essential model (usually `text_model`) should be required;
  optional models can stay blank.
- **Do not reuse the same `id="agent-form"` on the New page if the New page
  only has a name form.** Give it its own DOM id (`id="agent-name-form"`) or
  LiveView tests break.
- **The wizard redirect uses `push_navigate`; switching tabs uses
  `push_patch`.** `push_navigate` on every save would break the wizard UX.
- **Default tab should be safe:** if `params["tab"]` is unknown, fall back to
  the first tab (e.g. `:name`). Use `String.to_existing_atom/1` to avoid
  atom-table leaks.
- **Forms with `phx-change` must have an `id` attribute.** Without it, Phoenix
  LiveView emits a warning about missing form recovery. Add `id="agent-edit-form"`
  (or similar) to every `<.form>` tag that has `phx-change` or `phx-submit`.
- **For JSONB config toggles, use dedicated `phx-click` handlers + raw HTML
  inputs, not `<.input field={nil}>`.** `CoreComponents.input/1` requires a
  `Phoenix.HTML.FormField` struct — passing `nil` produces compile warnings.
  Use `<input type="checkbox" phx-click="toggle_X" checked={...}>` with a
  handler that reads the current config map, flips a key, and calls
  `update_agent` with the whole map.
- **When combining auto-save tabs with JSONB config sections,** keep the
  auto-save `handle_event("auto_save", ...)` for regular form fields, and add
  separate `handle_event("toggle_X", ...)` handlers for checkbox toggles that
  modify nested JSONB maps. The toggle handler should call
  `Agents.update_agent(agent, %{field => new_map})` directly, then refresh
  the changeset and agent assigns.
