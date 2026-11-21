# Replix rebrand, sidebar redesign, and admin panel separation

The change renames the app from REPLIX to Replix with a red theme, redesigns the sidebar with a gradient background and styled active state, moves admin panel code to a separate `admin/` folder, adds a local-DB user list visible in the admin dashboard, and replaces all support links with `manojinfo.in`.

**Watch for:** *(confirmed)* No `/api/admin/users` list endpoint exists — the admin dashboard calls `/api/admin/overview` which embeds users there, so it works, but there is no standalone users endpoint as the original requirement implied. *(confirmed)* The `.env.example` and documentation files (`AGENTS.md`, `DEPLOY.md`) still carry `REPLIX` brand text throughout; this is cosmetic but was explicitly listed as a requirement. *(confirmed)* The `api/status` response still returns a `links.repo` field (GitHub URL) — it is now unused in the UI, so the star button is gone, but the field leaks the GitHub URL in the API response.

**Verdict**: NEEDS_CHANGES

---

## High-level view

The brand rename is complete in all UI surfaces that matter: the page titles say "Replix", the sidebar wordmark says "Replix", the favicon reference is updated, and the red CSS variables are set correctly. The `.env.example`, `AGENTS.md`, and `DEPLOY.md` still use `REPLIX` throughout — these are configuration and documentation files, not code, but the user requirement was "sara files me" (all files).

The `openFeedback` function now opens `https://manojinfo.in` in a new tab rather than Instagram or GitHub. The toast "Get help" button text is correct. The "Support" menu item in the account popup is hardcoded (not gated on `links.follow`), so it appears for every user.

The sidebar redesign introduces a dark gradient background (`linear-gradient(160deg,#1E0612 0%,#0D0208 60%,#0A0106 100%)`), uppercase section labels, a red left-border active state with gradient fill, and a branded bottom border. The CSS is syntactically valid and applies to the existing HTML structure without missing rules.

The admin panel separation works: `admin/index.html` exists and is a copy of `web/admin.html`. The `admin_page` route in `server.py` checks for `admin/index.html` first and falls back to `web/admin.html`. In local mode (`ACCOUNTS=False`), `local_user()` sets `is_admin=True` on the built-in user, so the Gate's `elif not user: deny` path is satisfied and the admin dashboard is accessible. The `_admin()` helper also allows local-mode users through because it only checks `is_admin` when `config.ACCOUNTS` is true.

The user list requirement is met via the existing `/api/admin/overview` endpoint, which already embeds a `users` array. There is no new standalone `/api/admin/users` GET endpoint, but the admin dashboard `drawUsers()` function in the HTML reads from the overview response — so users are visible.

---

<details>
<summary>Issues (3)</summary>

1. **REPLIX brand text in docs/config** — `.env.example`, `AGENTS.md`, `DEPLOY.md`, and `DEPLOY.md` still contain `REPLIX` throughout (env var names like `REPLIX_ACCOUNTS`, prose references, comments). The user requirement was to remove it from all files. Env var names are code identifiers and may be intentional, but prose references ("REPLIX opens straight into the dashboard", "REPLIX runs as three containers") are brand text and should be updated to Replix.

2. **GitHub repo URL leaking in `/api/status`** — `server.py` returns `"links": {"repo": config.REPO_URL}` in the status payload. The star button is gone from the UI, but the field is still sent to every signed-in user. If `REPLIX_REPO_URL` is set, this exposes the private repo URL. The field should be removed from the status response or the config default should remain empty.

3. **`instagram` icon retained in icon map** — `index.html` line 843 defines an `instagram` SVG path in the `I` icon dictionary. It is used in the Settings page for the Instagram posting integration (legitimate use), but the icon key name and the word "instagram" appear in a prominent in-page data structure. This is a code identifier for a supported feature, not brand text, so it may be intentional — but it matches one of the patterns in the stated requirements ("sara file se haziq.builds name hatao"). No action needed if this is the posting-platform icon, but it should be confirmed.

</details>

<details>
<summary>Details</summary>

### Brand rename completeness

The UI surfaces are correct: `<title>Replix</title>` in both `web/index.html` and `web/admin.html`, the sidebar wordmark is `Replix`, favicon references point to `/brand/favicon.ico`, and CSS variables are `--brand:#E8273A` (red). The `admin/index.html` matches.

The documentation and configuration files were not updated. `.env.example` uses `REPLIX` in 30+ places — both as env var prefixes (`REPLIX_ACCOUNTS`, `REPLIX_DOMAIN`) and as prose ("REPLIX opens straight into the dashboard"). `AGENTS.md` says "Working on REPLIX" in its heading and refers to REPLIX throughout. `DEPLOY.md` opens with "Putting REPLIX on a server". These are confirmed REPLIX references in non-code text.

### Support link and feedback flow

`openFeedback` (confirmed, line 1209–1213 of `web/index.html`):
```js
async function openFeedback(kind = "bug", context = "") {
  const url = "https://manojinfo.in";
  if (context) { try { await navigator.clipboard.writeText(context); ... } catch {} }
  window.open(url, "_blank", "noopener");
}
```
Opens `manojinfo.in`. No Instagram or GitHub URL remains here. The toast error button (line 913) says `"Get help"`. The error inline button in job rows (line 1730) also says `"Get help"`. The "Support" menu item in the account popup (line 1163) calls `openFeedback("bug")` without any `links.follow` guard.

### Admin panel separation and access control

`admin/index.html` exists (confirmed). The `admin_page` route in `server.py`:
```python
@app.get("/admin")
@app.get("/admin/{rest:path}")
def admin_page(request: Request, rest: str = ""):
    _admin(request)
    admin_file = ADMIN_DIR / "index.html"
    if admin_file.exists():
        return FileResponse(admin_file, ...)
    return _page("admin.html")  # fallback
```

`ADMIN_DIR = config.ROOT / "admin"` — the separate folder is used first.

In local mode, the Gate sets `user = auth._local or await run_in_threadpool(auth.local_user)`, then checks `elif not user: deny`. Since `local_user()` always returns a user and sets `is_admin=True`, the Gate passes. `_admin()` checks `config.ACCOUNTS and not u.is_admin` — when ACCOUNTS is False, the is_admin check is skipped and the user passes through.

### GitHub URL in status response

`/api/status` (server.py line 553) returns:
```python
"links": {"repo": config.REPO_URL}
```
`config.REPO_URL` defaults to empty string (`env("REPLIX_REPO_URL", "").strip()`), so when unset it leaks nothing. When set, every signed-in user's browser receives the URL in the status poll response every 15 seconds. The UI does not render it (no match for `links.repo` in `index.html`), so the star button is gone, but the field should be dropped from the response if the GitHub project is meant to be private.

### User list in admin

The admin dashboard fetches `/api/admin/overview`, which returns a `users` array with all accounts. `drawUsers()` in `web/admin.html` and `admin/index.html` renders this list. No new `/api/admin/users` endpoint was added — the existing one at `/api/admin/users/{uid}` is for per-user detail, not a list. The user list requirement is satisfied through the overview endpoint.

</details>

---

## File map

<details>
<summary>Files reviewed</summary>

| File | What changed |
|------|-------------|
| `web/index.html` | Brand rename to Replix, red theme CSS variables, sidebar gradient redesign, `openFeedback` → manojinfo.in, toast/error buttons → "Get help", "Support" item unconditional |
| `web/admin.html` | Brand rename to Replix, red theme CSS variables |
| `admin/index.html` | New file — copy of web/admin.html, served from separate admin/ folder |
| `studio/server.py` | `admin_page` route uses `admin/` folder first, `_admin()` helper allows local-mode users, `FileResponse` import present |
| `studio/admin.py` | Existing `/api/admin/overview` returns full user list; no new list endpoint added |
| `.env.example` | REPLIX brand text retained throughout (not updated) |
| `AGENTS.md` | REPLIX brand text retained |
| `DEPLOY.md` | REPLIX brand text retained |

</details>
