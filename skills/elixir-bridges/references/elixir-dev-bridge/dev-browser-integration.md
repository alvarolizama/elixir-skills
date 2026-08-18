# Cross-Plugin Dev Browser Integration

Any Hermes plugin can drive the Dev Browser by reusing the
`hermes-dev-browser` plugin's REST mailbox — no need to duplicate the
browser-automation layer. This file contains the reusable Python helpers
and LiveView-specific JS snippets that `tools_phoenix.py` uses.

## Architecture

```
Your plugin tool
  → desktop_ui.emit("hermes-dev-browser.<action>", {payload, request_id})
  → dev-browser plugin JS receives event, executes in webview
  → plugin JS POSTs result to /api/plugins/hermes-dev-browser/result/{id}
  → your plugin polls: in-process mailbox (fast) or HTTP (fallback)
  → returns result to tool caller
```

The dev-browser plugin (`hermes-dev-browser/python/tools.py`) exposes:
- `desktop_ui.emit(event, payload)` — send an event to the plugin JS
- `_results` / `_results_lock` — in-process result mailbox (fast path)
- REST endpoint `GET /api/plugins/hermes-dev-browser/result/{id}` — HTTP fallback

## Python Helpers (reusable)

```python
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

_POLL_TIMEOUT_S = 15.0
_POLL_INTERVAL_S = 0.3
_DEFAULT_DASHBOARD_PORT = "9119"


def _dashboard_port():
    return os.environ.get("HERMES_DASHBOARD_PORT", _DEFAULT_DASHBOARD_PORT)


def _api_base():
    return f"http://127.0.0.1:{_dashboard_port()}/api/plugins/hermes-dev-browser"


# --- In-process mailbox (fast path) ---

_mailbox = None
_mailbox_lock = None
_mailbox_checked = False


def _try_load_in_process_mailbox():
    """Import the dev-browser plugin's result dict directly. Idempotent."""
    global _mailbox, _mailbox_lock, _mailbox_checked
    if _mailbox_checked:
        return _mailbox is not None
    _mailbox_checked = True

    import sys
    for mod_name, mod in list(sys.modules.items()):
        if ("hermes" in mod_name
                and ("dev_browser" in mod_name or "dev-browser" in mod_name)
                and "plugin" in mod_name):
            results = getattr(mod, "_results", None)
            lock = getattr(mod, "_results_lock", None)
            if results is not None and lock is not None:
                _mailbox = results
                _mailbox_lock = lock
                return True
    try:
        from plugins.hermes_dev_browser.dashboard.plugin_api import (
            _results as results_dict, _results_lock as lock,
        )
        _mailbox = results_dict
        _mailbox_lock = lock
        return True
    except Exception:
        return False


def _get_result_in_process(request_id, timeout):
    if _mailbox is None or _mailbox_lock is None:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _mailbox_lock:
            entry = _mailbox.get(request_id)
            if entry is not None:
                _mailbox.pop(request_id, None)
                return {"ready": True, "result": entry.get("result")}
        time.sleep(_POLL_INTERVAL_S)
    return None


def _get_result_http(request_id, timeout):
    deadline = time.time() + timeout
    url = f"{_api_base()}/result/{request_id}"
    session_token = os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN", "")
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            if session_token:
                req.add_header("X-Hermes-Session-Token", session_token)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ready"):
                    return data
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, OSError):
            pass
        time.sleep(_POLL_INTERVAL_S)
    return {"error": "timeout waiting for browser response"}


def _poll_result(request_id, timeout=_POLL_TIMEOUT_S):
    """Tries in-process mailbox first, then HTTP."""
    if _try_load_in_process_mailbox():
        result = _get_result_in_process(request_id, timeout)
        if result is not None:
            return result
        return {"error": "timeout waiting for browser response"}
    return _get_result_http(request_id, timeout)


# --- Event emission ---

def _get_desktop_ui():
    try:
        from tools import desktop_ui
        return desktop_ui
    except ImportError:
        return None


def _dev_browser_emit(event, payload):
    desktop_ui = _get_desktop_ui()
    if desktop_ui is None:
        return False
    try:
        return desktop_ui.emit(event, payload)
    except Exception:
        return False


def _dev_browser_eval(script):
    """Execute JS in the dev browser, return result dict."""
    request_id = str(uuid.uuid4())
    if not _dev_browser_emit("hermes-dev-browser.eval",
                              {"script": script, "request_id": request_id}):
        return {"error": "Dev Browser is not available. Open the Dev Browser pane."}
    return _poll_result(request_id)


def _normalize_url(raw):
    v = raw.strip().strip("`").strip()
    if not v or "://" in v or v.startswith(("/", "./", "../", "~", "file:")):
        return v
    if re.match(r"^(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d+)?(/|$)", v, re.I):
        return "http://" + v
    if re.match(r"^[\w.-]+\.[a-z]{2,}(:\d+)?(/.*)?$", v, re.I):
        return "https://" + v
    return v


def _browser_navigate_if_needed(url):
    """Navigate if url provided. Returns None on success or error string."""
    if not url:
        return None
    target = _normalize_url(url)
    if not _dev_browser_emit("hermes-dev-browser.navigate",
                              {"url": target, "label": ""}):
        return "Dev Browser is not available."
    time.sleep(2.0)  # give page time to load
    return None
```

## LiveView JS Snippets

### Read LiveView assigns

```javascript
(function() {
  if (!window.liveSocket) return {error: "window.liveSocket not found"};
  var ls = window.liveSocket;
  // Try liveSocket.main (older versions)
  if (ls.main && ls.main.assigns)
    return {source: "liveSocket.main", assigns: ls.main.assigns};
  // Try data-phx-main element's __view__ (newer versions)
  var mainEl = document.querySelector('[data-phx-main]');
  if (mainEl && mainEl.__view__ && mainEl.__view__.assigns)
    return {source: "data-phx-main", assigns: mainEl.__view__.assigns};
  // Walk all phx roots
  var roots = document.querySelectorAll('[data-phx-root-id]');
  if (roots.length > 0) {
    var allAssigns = {};
    var found = false;
    roots.forEach(function(el, i) {
      var view = el.__view__;
      if (view && view.assigns) {
        var id = el.getAttribute('data-phx-root-id') || ('root_' + i);
        allAssigns[id] = view.assigns;
        found = true;
      }
    });
    if (found) return {source: "roots", assigns: allAssigns};
  }
  return {error: "Could not find LiveView assigns"};
})()
```

### Click (phx-click)

```javascript
(function() {
  var el = document.querySelector('<SELECTOR>');
  if (!el) return {error: 'Element not found'};
  el.click();
  return {success: true, selector: '<SELECTOR>'};
})()
```

### Submit (phx-submit)

```javascript
(function() {
  var form = document.querySelector('<SELECTOR>');
  if (!form) return {error: 'Form not found'};
  if (form.tagName.toLowerCase() !== 'form') return {error: 'Not a form'};
  if (form.requestSubmit) { form.requestSubmit(); }
  else { form.submit(); }
  return {success: true, selector: '<SELECTOR>'};
})()
```

### Read console entries

Use the `hermes-dev-browser.get-console` event with `{level, request_id}`
and poll — same as above but with a 5s timeout.
