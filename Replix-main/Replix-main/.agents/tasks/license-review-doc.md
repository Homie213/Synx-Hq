# HWID-Bound License Key System

This change introduces a full license gating system for Replix: a `license_keys` and `license_activations` schema, a `license.py` module for validation and activation logic, server routes for activation and status, an admin Keys tab for creating and revoking keys, and a client-side lock overlay that blocks the UI until a valid plan key is entered. The system is designed to bind one key to at most N devices, enforce per-device HWID uniqueness, and re-activate silently when the same user+HWID pair re-submits a key. The overlay is rendered client-side and gated by the license field on every `/api/status` poll.

**Watch for:**
- **confirmed** — The activation endpoint accepts a client-supplied HWID. A user can pass any HWID string to register multiple machines under the same key, bypassing the per-device binding entirely.
- **confirmed** — `/api/status` calls `lic.license_status(me_.id, lic.get_hwid())` using the *server's* HWID, not the client's HWID. This means the status will always return `active: False` in a deployed multi-user environment where the server and the user's machine are different hosts.
- **confirmed** — The lock overlay is enforced only in JavaScript. No server route checks `license.active` before allowing AI or video processing requests. The gate is cosmetic.
- **likely** — The admin `revoke_device` endpoint accepts a raw `act_id` integer from the URL with no ownership check confirming the activation record belongs to the key in the URL path.

**Verdict**: NEEDS_CHANGES

---

## High-level view

The schema is sound: `license_keys` and `license_activations` are properly defined with foreign keys, cascade deletes, and indexes on `user_id` and `hwid`. All queries go through SQLAlchemy's ORM layer with bound parameters — no f-strings or string interpolation in SQL. The admin routes are gated by `_admin()`, which enforces `is_admin` in production and blocks non-admins with a 404.

The activation flow has a structural correctness problem. The server computes `get_hwid()` for the status check but the activate endpoint also accepts a `hwid` from the request body — and uses that body value directly. These two HWIDs come from different machines (the server and the user's machine), so they will never match in any deployed scenario. This makes the entire HWID-binding mechanism incoherent: activation stores the client-supplied HWID, but `license_status` and `/api/status` query against the server's own HWID.

The lock overlay is a client-side only gate. No server route checks the license before serving AI inference, rendering, or upload requests. Any user who can authenticate can bypass the overlay by calling the API directly.

The re-activation path (same user+hwid on an existing activation) correctly updates `last_seen` and returns current status. The max-devices check and cross-account HWID check happen inside a single `engine.begin()` transaction, so they are atomic. Key generation uses `secrets.choice`, making brute-force enumeration infeasible.

---

<details>
<summary>Issues (5)</summary>

1. **Client-supplied HWID accepted at activation** — `/api/license/activate` reads `hwid` from `body.get("hwid", "")` and stores it directly. Any client can pass an arbitrary string, registering unlimited fake devices or spoofing another user's HWID. Fix: ignore the body's HWID in the server route and always compute it server-side — but see the next issue for why that also needs rethinking.

2. **Server HWID used for license status in a multi-user deployment** — `license_status_route` and `/api/status` both call `lic.get_hwid()`, which returns the hardware fingerprint of the *server process*, not the client's machine. In production, `license_status` will always return `{"active": False, "reason": "no_license"}` for every user because the server's HWID will never match any activation stored against a user's desktop HWID. The HWID fingerprinting model assumes a single-machine deployment (like an Electron/desktop app). If this is intended as a web service, HWID binding needs to move to the client binary, not the server. If it's desktop-only, the architecture is consistent but needs to be documented and the server routes removed in favor of local-only validation.

3. **Lock overlay is a UI gate only — no server enforcement** — `checkLicense()` and the `.lock-overlay` are client-side only. No middleware or route handler checks `license.active` before processing requests to `/api/upload`, AI endpoints, or the render pipeline. Any authenticated user can call the API directly and get full functionality regardless of license status.

4. **`admin_revoke_device` has no ownership check on `act_id`** — `POST /api/admin/keys/{key}/devices/{act_id}/revoke` passes `act_id` directly to `lic.admin_revoke_device(act_id)`, which issues `UPDATE license_activations WHERE id = act_id`. There is no check that the activation record belongs to the `key` in the URL path. An admin can revoke any activation by guessing or knowing its integer ID, regardless of which key it belongs to. Add a `WHERE id = act_id AND key = key` condition.

5. **`/api/status` unconditionally calls `license_status` for every authenticated request** — `lic.license_status` performs a database join and an `UPDATE last_seen` on every 15-second poll from every logged-in user. At scale this generates significant write load. Consider caching the status in memory (keyed by `user_id + hwid`) with a short TTL, or only updating `last_seen` less frequently.

</details>

---

<details>
<summary>Details</summary>

## HWID binding is split across two trust boundaries

The `get_hwid()` function computes a fingerprint from `platform.node()`, `uuid.getnode()` (MAC address), `platform.processor()`, the OS username, and `platform.machine()`. This is a reasonable desktop fingerprint — stable across reboots, changes on hardware swap.

The problem is that in the activation endpoint, the server accepts the HWID from the client:

```python
hwid = str(body.get("hwid", "")).strip() or lic.get_hwid()
```

The fallback `lic.get_hwid()` computes the *server's* HWID when the body is empty. For the UI flow, the browser first calls `GET /api/license/hwid` (which returns the server's HWID), then submits that value back in the activate POST. So in the web flow, both the activation and the status check use the server's HWID — which makes the system internally consistent for single-machine local deployments (where the server runs on the same machine as the user), but completely wrong for any cloud-hosted deployment.

If this is a web service with remote users, HWID binding cannot live in the server process at all. The fingerprint must be computed inside a client binary (Electron app, desktop CLI) and sent in a signed payload the server can't trivially spoof. As currently written, the HWID stored in `license_activations` is whatever string the client POST body says it is, with no attestation.

## Admin Keys tab is present in both admin panels

Both `web/admin.html` and `admin/index.html` include `keys` in their `TABS` constant and implement `drawKeys`, `refreshKeys`, `openCreateKey`, `doCreateKey`, `revokeKey`, and `openKeyDevices`. The UI is functionally identical between the two files, which creates a maintenance burden: any fix must be applied in both places.

## `checkLicense()` call coverage

`checkLicense()` is called in every code path that sets or refreshes `S.status`:
- After initial `/api/status` load on page boot
- In the 15-second polling interval
- After `activateLicense()` completes
- Inside `drawShell()` (called on every render pass)
- After settings saves that refresh status

Coverage is thorough for the UI gate. The gap is that the gate is entirely in the browser — there is nothing on the server that enforces it.

## `license_status` queries and the last_seen update

`license_status` runs a JOIN across `license_keys` and `license_activations`, then immediately opens a second connection to do an `UPDATE last_seen`. Two round-trips per call is avoidable (the update could be batched or rate-limited), and because `/api/status` calls it on every 15-second poll for every authenticated user, this is a confirmed write-amplification concern at any meaningful user count.

</details>

---

<details>
<summary>File map</summary>

- `studio/license.py` — New module: HWID fingerprinting, key generation, activation flow, re-activation, max-devices enforcement, admin CRUD helpers.
- `studio/db.py` — Added `license_keys` and `license_activations` table definitions with indexes and FK constraints.
- `studio/server.py` — Added `/api/license/hwid`, `/api/license/activate`, `/api/license/status`, and five `/api/admin/keys/*` routes; added `license` field to `/api/status` response.
- `web/index.html` — Added `.lock-overlay` CSS, `checkLicense()`, `activateLicense()`, `lockShowTab()` JS functions, and the lock overlay HTML block at the end of body.
- `web/admin.html` — Added `keys` tab to `TABS`, `drawKeys`, `refreshKeys`, `openCreateKey`, `doCreateKey`, `revokeKey`, `openKeyDevices` functions.
- `admin/index.html` — Same Keys tab additions as `web/admin.html` (duplicate implementation).

Full diff: `git diff main -- studio/license.py studio/db.py studio/server.py web/index.html web/admin.html admin/index.html`

</details>
