# Co-located JS hooks: clipboard copy fallback

## Symptom
In production (served over plain **HTTP**), a copy button throws:
`Uncaught TypeError: Cannot read properties of undefined (reading 'writeText')`.

The `navigator.clipboard` API is **only defined in secure contexts** — HTTPS
or `localhost`. On HTTP it is `undefined`, so calling
`navigator.clipboard.writeText(...)` crashes. Dev (`localhost`) works fine,
which is why it slips past local testing.

## Robust copy hook pattern
Guard for the API, else fall back to the classic `document.execCommand('copy')`
via a temporary `<textarea>` (works in plain HTTP):

```js
// <script :type={Phoenix.LiveView.ColocatedHook} name=".CopyApiToken">
export default {
  mounted() {
    this.el.addEventListener("click", () => {
      const text = /* the string to copy */;
      if (!text) return;
      const copied = () => {
        // swap copy-icon <-> check-icon, hide check after ~1500ms
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(copied);
      } else {
        this.copyFallback(text);
        copied();
      }
    });
  },
  copyFallback(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "absolute";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    try { document.execCommand("copy"); } catch (_e) {}
    document.body.removeChild(ta);
  }
};
```

Keep the copy source in a `data-` attribute (e.g. `data-token={@value}`) so the
hook copies the real value regardless of what is visually rendered (e.g. masked
token vs full token).

## Long-term
The fallback is a band-aid. The real fix is serving the app over HTTPS so
`navigator.clipboard` exists and secrets don't travel in clear. Offer to add
TLS (Caddy/certbot) whenever you patch an HTTP copy bug.

## Pitfalls
- Apply the same fallback to EVERY copy hook in the app, not just the one
  reported — grep for `navigator.clipboard.writeText` and fix the whole class.
- If you add a show/hide (eye) toggle for a secret, reset it to hidden when the
  value is regenerated (`show_token: false` in the regenerate handler).
- After adding new `gettext("...")` strings, run `mix gettext.extract` so the
  `.pot` stays in sync before committing.
