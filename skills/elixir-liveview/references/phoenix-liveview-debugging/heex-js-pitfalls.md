# HEEx + JS Pitfalls (Phoenix LiveView)

Common compilation and runtime errors when mixing `Phoenix.LiveView.JS` with HEEx templates. These apply to ALL Phoenix LiveView projects, not just my_app.

## `%JS{}` struct literal in HEEx

**Error:** `** (CompileError) expected key-value pairs in a map`

```heex
<%!-- WRONG — triggers compile error --%>
<button phx-click={%JS{push("toggle_token"), JS.dispatch("js:copy", to: "#target")}}>
```

The `%JS{}` struct constructor is not valid HEEx expression syntax. The HEEx engine tries to parse it as a map literal and fails.

**Fix:** Use `Phoenix.LiveView.JS` module functions directly, or use plain `phx-click` with string event names:

```heex
<%!-- CORRECT — simple event name --%>
<button phx-click="toggle_token">Click</button>

<%!-- CORRECT — JS function chain (when JS is aliased) --%>
<button phx-click={JS.push("toggle_token") |> JS.dispatch("js:copy", to: "#target")}>Click</button>
```

## `phx-hook` expects a string hook name, not a JS struct

```heex
<%!-- WRONG — compiles but doesn't work at runtime --%>
<button phx-hook={%JS{} |> JS.dispatch("js:copy", to: "#target")}>Copy</button>

<%!-- CORRECT — string hook name referencing a colocated hook --%>
<button phx-hook=".CopyToken">Copy</button>
```

## Colocated hook placement

Colocated hooks (`<script :type={Phoenix.LiveView.ColocatedHook} name=".HookName">`) must be inside the **main `render/1` function's `~H` block**.

**Common mistake:** defining the hook inside a `defp` function component (`defp api_keys_section(assigns) do ~H"""...""" end`). Phoenix won't find it there.

```heex
<%!-- In render/1's ~H block --%>
<Layouts.app flash={@flash}>...</Layouts.app>

<%!-- ✅ Hook placed here, inside render/1's ~H --%>
<script :type={Phoenix.LiveView.ColocatedHook} name=".CopyToken">
  export default {
    mounted() {
      this.el.addEventListener("click", () => {
        const target = document.getElementById("target-id");
        if (target) {
          navigator.clipboard.writeText(target.textContent.trim());
        }
      });
    }
  };
</script>
```

## `data-*` attributes on Phoenix components

Phoenix component functions (e.g. `<.icon>`, `<.input>`, `<.button>`) don't accept arbitrary HTML attributes like `data-*`.

**Error:** `undefined attribute "data-copy-icon" for component DranWeb.CoreComponents.icon/1`

```heex
<%!-- WRONG --%>
<.icon name="hero-x" class="size-4" data-copy-icon />

<%!-- CORRECT — wrap in raw HTML element --%>
<span data-copy-icon><.icon name="hero-x" class="size-4" /></span>
```

## Copy-to-clipboard pattern

When adding a copy button with visual feedback (icon swap), use a colocated hook:

1. Define the hook in `render/1`:
```heex
<script :type={Phoenix.LiveView.ColocatedHook} name=".CopyToken">
  export default {
    mounted() {
      this.el.addEventListener("click", () => {
        const target = document.getElementById(this.el.dataset.target);
        if (target) {
          navigator.clipboard.writeText(target.textContent.trim()).then(() => {
            const icon = this.el.querySelector("[data-copy-icon]");
            const check = this.el.querySelector("[data-check-icon]");
            if (icon && check) {
              icon.classList.add("hidden");
              check.classList.remove("hidden");
              setTimeout(() => {
                icon.classList.remove("hidden");
                check.classList.add("hidden");
              }, 1500);
            }
          });
        }
      });
    }
  };
</script>
```

2. Use it with icon swap spans:
```heex
<button
  id="copy-btn"
  phx-hook=".CopyToken"
  data-target="api-token-display"
  class="btn btn-ghost btn-sm"
>
  <span data-copy-icon><.icon name="hero-clipboard-document" class="size-4" /></span>
  <span data-check-icon class="hidden">
    <.icon name="hero-clipboard-document-check" class="size-4" />
  </span>
</button>
```
