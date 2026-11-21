# Implementation Plan — Email OTP / Two-step verification

## Codebase findings

| File | Key facts |
|---|---|
| `studio/db.py` | Tables declared as `sa.Table(...)` module-level globals. Last table before this change is `license_activations` (line ~108). `meta.create_all` in `init()` picks them up automatically — no migration step needed. |
| `studio/admin_otp.py` | Reference OTP implementation: in-memory `dict` keyed by identity, stores `(hash, expires_at, attempts)`, TTL+max-tries enforcement, background thread for delivery. Use same pattern. |
| `studio/auth.py` | `get_user(uid)` returns a SQLAlchemy `Row` or `None`. `public(u)` reads `u.id`, `u.email`, `u.name`, `u.is_admin`, `u.password_hash`, `u.google_sub`, `u.created_at`. `start_session(uid, ip, agent)` → token str. `cookie_args(token)` → dict for `set_cookie`. `throttle(key, limit, window)` raises `AuthError` on excess. |
| `studio/mailer.py` | `ready() -> bool` (needs `SMTP_HOST` + `MAIL_FROM`). `send(to, subject, title, intro, button, link, outro) -> bool`. Sends in background thread. |
| `studio/server.py` | `from . import admin_otp` is at line 28. Login route is `@app.post("/api/auth/login")` at line 513 (function body lines 515–524). `_me(request)` defined at line ~302. `_ip(request)` defined at ~259. `_signed_in(request, user, first)` defined at ~489. `config.HTTPS` imported via `from . import ... config`. `from . import mailer` is used inline in `auth.py` and in other routes. |
| `web/auth.html` | Single `<script>` at the bottom. Form submit handler at line ~180 in that script. No OTP dialog exists yet. `dest` variable already holds the post-login redirect target. |
| `web/index.html` | `drawSettings()` async function at line 2101. Security tab `if` block at line 2133–2143. The whole block sets `body.innerHTML` to a template literal string ending with the Delete account `</section>\``;` at line 2142. `send(path, body, method)` defined at line 931 (arrow function). `api(path, opt)` at line 924. `toast(msg, kind)` at line 932. `esc()` function already defined in the file. |

---

## Plan

- [ ] 1. Add two new tables to `studio/db.py`.
      Append `totp_settings` and `device_trusts` table definitions after the `license_activations` table (after the `sa.Index("lic_act_hwid", "hwid")` closing line, before the blank line above `def init()`). No other change to `db.py`.
      ```python
      totp_settings = sa.Table(
          "totp_settings", meta,
          sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
          sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
          sa.Column("enabled_at", sa.Float),
      )

      device_trusts = sa.Table(
          "device_trusts", meta,
          sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
          sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
          sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
          sa.Column("created_at", sa.Float, nullable=False),
          sa.Column("expires_at", sa.Float, nullable=False),
          sa.Column("device_name", sa.String(200), nullable=False, server_default=""),
      )
      ```
      Files: `studio/db.py`
      Verify: `python -c "import ast; ast.parse(open('studio/db.py').read()); print('db.py OK')"` from the repo root — must print `db.py OK`. Also run `python -c "from studio import db; db.init(); print('tables ok')"` with no DATABASE_URL set (it uses SQLite) — must succeed without error.

- [ ] 2. Create `studio/email_otp.py`.
      Model it on `studio/admin_otp.py`. In-memory store keyed by `user_id` (string). Constants: `OTP_TTL = 600` (10 min), `OTP_MAX_TRIES = 5`, `TRUST_DAYS = 30`. Use `threading.Lock` for all dict access.

      Functions to implement:

      **`is_enabled(user_id: str) -> bool`**
      Query `db.totp_settings` where `user_id == user_id` and `enabled == True`. Return `bool`.

      **`set_enabled(user_id: str, on: bool)`**
      Upsert into `totp_settings`. For SQLite compatibility use delete-then-insert pattern (like `auth._make_link` does): delete existing row for that user_id, then insert with the new value. Set `enabled_at` to `time.time()` when enabling, `None` when disabling.

      **`generate_and_send(user_id: str, email: str)`**
      Generate `str(secrets.randbelow(900000) + 100000)` (always 6 digits). Hash it with SHA-256 (`hashlib.sha256`). Store `(hash, time.time() + OTP_TTL, 0)` under `_otps[user_id]` inside the lock. Call `mailer.send(email, "Your Replix login code", "Your Replix login code", "Your one-time login code is:", otp, "#", "This code expires in 10 minutes. If you didn't try to sign in, ignore this email.")`. The OTP code itself is the `button` argument (the large display text in the email template).

      **`verify(user_id: str, otp: str) -> bool`**
      Inside lock: look up `_otps.get(user_id)`. If missing, return False. If expired (`time.time() > expires_at`), delete entry, return False. If attempts >= `OTP_MAX_TRIES`, delete entry, return False. If hash doesn't match, increment attempts, return False. On match, delete entry, return True.

      **`is_trusted_device(user_id: str, token: str) -> bool`**
      Hash the token. Query `device_trusts` where `user_id == user_id` and `token_hash == hash` and `expires_at > time.time()`. Return whether a row was found.

      **`trust_device(user_id: str, device_name: str) -> str`**
      Generate `secrets.token_urlsafe(32)`. Hash it. Insert into `device_trusts` with `created_at=time.time()`, `expires_at=time.time() + TRUST_DAYS*86400`, `device_name=device_name[:200]`. Return the plain token.

      **`revoke_all_trusted(user_id: str)`**
      Delete all rows from `device_trusts` where `user_id == user_id`.

      Imports needed: `hashlib`, `secrets`, `threading`, `time`, `sqlalchemy as sa`, `from . import config, db, mailer`.

      Files: `studio/email_otp.py` (new file)
      Verify: `python -c "import ast; ast.parse(open('studio/email_otp.py').read()); print('email_otp.py OK')"` — must print `email_otp.py OK`.

- [ ] 3. Modify `studio/server.py` — import and login route.

      **3a.** On line 28, after `from . import admin_otp`, add:
      ```python
      from . import email_otp
      ```

      **3b.** Replace the entire `login` function body (lines 514–524, keeping the `@app.post` decorator). The new function:
      ```python
      @app.post("/api/auth/login")
      def login(request: Request, body: dict = Body(...)):
          email_addr = str(body.get("email", ""))
          trust_token = str(body.get("trust_token", "")).strip()
          try:
              auth.throttle("login-ip:" + _ip(request), 30, 600)
              auth.throttle(f"login:{email_addr.strip().lower()[:254]}:{_ip(request)}", 8, 600)
              auth.throttle("login:" + email_addr.strip().lower()[:254], 60, 600)
              user = auth.login(email_addr, str(body.get("password", "")))
          except auth.AuthError as e:
              raise HTTPException(400, str(e))
          # Check 2FA
          if email_otp.is_enabled(user.id):
              if trust_token and email_otp.is_trusted_device(user.id, trust_token):
                  return _signed_in(request, user, False)
              from . import mailer
              if mailer.ready():
                  email_otp.generate_and_send(user.id, user.email)
                  return JSONResponse({"needs_otp": True, "user_id": user.id})
              # Mailer not configured: skip 2FA gracefully
          return _signed_in(request, user, False)
      ```

      Files: `studio/server.py`
      Verify: `python -c "import ast; ast.parse(open('studio/server.py').read()); print('server.py OK')"` — must print `server.py OK`.

- [ ] 4. Add three new API routes to `studio/server.py`.
      Insert these three routes immediately after the `login` function (after `return _signed_in(request, user, False)` and before `@app.post("/api/auth/logout")`).

      **Route 1: `/api/auth/login/otp`**
      ```python
      @app.post("/api/auth/login/otp")
      def login_otp(request: Request, body: dict = Body(...)):
          try:
              auth.throttle("otp-ip:" + _ip(request), 10, 300)
          except auth.AuthError:
              raise HTTPException(429, "Too many attempts. Wait a few minutes.")
          user_id = str(body.get("user_id", "")).strip()
          otp = str(body.get("otp", "")).strip()
          remember = bool(body.get("remember", False))
          device_name = str(body.get("device_name", ""))[:200] or "Unknown device"
          if not user_id or not otp:
              raise HTTPException(400, "Missing user_id or otp.")
          if not email_otp.verify(user_id, otp):
              raise HTTPException(400, "Wrong or expired code. Try again or request a new one.")
          u = auth.get_user(user_id)
          if not u:
              raise HTTPException(400, "Account not found.")
          if remember:
              trust_token = email_otp.trust_device(u.id, device_name)
              token = auth.start_session(u.id, _ip(request), request.headers.get("user-agent", ""))
              resp = JSONResponse({"user": auth.public(u), "trust_token": trust_token})
              resp.set_cookie(**auth.cookie_args(token))
              resp.set_cookie("replix_trust", trust_token, max_age=30 * 86400, httponly=True,
                              samesite="lax", secure=config.HTTPS, path="/")
              return resp
          return _signed_in(request, u, False)
      ```

      **Route 2: `/api/auth/2fa/status`**
      ```python
      @app.post("/api/auth/2fa/status")
      def twofa_status(request: Request):
          me = _me(request)
          if not me:
              raise HTTPException(401, "Please sign in.")
          return {"enabled": email_otp.is_enabled(me.id)}
      ```

      **Route 3: `/api/auth/2fa/toggle`**
      ```python
      @app.post("/api/auth/2fa/toggle")
      def twofa_toggle(request: Request, body: dict = Body(...)):
          me = _me(request)
          if not me:
              raise HTTPException(401, "Please sign in.")
          on = bool(body.get("enabled", False))
          if on:
              from . import mailer
              if not mailer.ready():
                  raise HTTPException(400, "Email is not configured on this server. Set up SMTP first.")
          email_otp.set_enabled(me.id, on)
          if not on:
              email_otp.revoke_all_trusted(me.id)
          return {"enabled": on}
      ```

      Files: `studio/server.py`
      Verify: `python -c "import ast; ast.parse(open('studio/server.py').read()); print('server.py OK')"` — must print `server.py OK`.

- [ ] 5. Modify `web/auth.html` — OTP dialog and flow.
      All changes are inside the single `<script>` block at the bottom of the file.

      **5a. Modify the form submit handler.**
      The existing handler (starting with `$("f").addEventListener("submit", async e => {`) sends login and immediately redirects on success. Replace it with:
      ```javascript
      $("f").addEventListener("submit", async e => {
        e.preventDefault(); $("err").classList.remove("on");
        const email = $("email").value.trim(), password = $("password").value;
        if (!email || !password) return fail("Enter your email and password.");
        $("go").disabled = true;
        try {
          const trust_token = localStorage.getItem("replix_trust_token") || "";
          const r = await fetch(up ? "/api/auth/signup" : "/api/auth/login", {method:"POST", headers:{"Content-Type":"application/json"},
            body:JSON.stringify({email, password, name:$("name").value.trim(), trust_token})});
          const d = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Something went wrong. Try again.");
          if (!up && d.needs_otp) { showOTPStep(d.user_id, email); return; }
          location.href = dest;
        } catch (err) { fail(err.message); $("go").disabled = false; }
      });
      ```
      Note: `$("go").disabled` is NOT re-enabled after `showOTPStep` because the main form is hidden by the dialog at that point; re-enabling happens inside `showOTPStep`.

      **5b. Add OTP JS functions** (append after the form submit handler, before `</script>`):
      ```javascript
      let _otpUserId = "";
      function showOTPStep(userId, email) {
        _otpUserId = userId;
        $("otpEmail").textContent = email;
        $("otpCode").value = "";
        $("otpErr").textContent = ""; $("otpErr").hidden = true;
        $("otpVerify").disabled = false;
        $("otpDlg").showModal();
        $("otpCode").focus();
        $("go").disabled = false;
      }
      async function submitOTP() {
        const otp = $("otpCode").value.replace(/\D/g, "");
        if (otp.length !== 6) { $("otpErr").textContent = "Enter the 6-digit code from your email."; $("otpErr").hidden = false; return; }
        $("otpVerify").disabled = true;
        $("otpErr").hidden = true;
        try {
          const remember = $("otpRemember").checked;
          const device_name = navigator.userAgentData?.platform || navigator.platform || "Browser";
          const r = await fetch("/api/auth/login/otp", {method:"POST", headers:{"Content-Type":"application/json"},
            body:JSON.stringify({user_id:_otpUserId, otp, remember, device_name})});
          const d = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Something went wrong.");
          if (remember && d.trust_token) {
            try { localStorage.setItem("replix_trust_token", d.trust_token); } catch {}
          }
          location.href = dest;
        } catch (err) {
          $("otpErr").textContent = err.message; $("otpErr").hidden = false;
          $("otpVerify").disabled = false;
        }
      }
      document.addEventListener("DOMContentLoaded", () => {
        const oc = $("otpCode");
        if (oc) {
          oc.addEventListener("input", () => { oc.value = oc.value.replace(/\D/g, "").slice(0, 6); });
          oc.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); submitOTP(); } });
        }
      });
      ```

      **5c. Add the OTP dialog HTML** between `</main>` and `</body>`:
      ```html
      <dialog id="otpDlg" style="border:1.5px solid #E1D9D3;border-radius:16px;padding:32px 28px;max-width:380px;width:100%;background:#fff;color:#211813">
        <h2 style="margin:0 0 8px;font-size:22px;font-weight:700;letter-spacing:-.02em;color:#2A0810">Check your email</h2>
        <p style="margin:0 0 20px;font-size:15px;color:#6D6159">We sent a 6-digit code to <b id="otpEmail"></b>. Enter it below.</p>
        <p id="otpErr" style="display:block;background:#FDECEE;color:#D3343F;padding:10px 13px;border-radius:10px;font-size:14px;font-weight:500;margin:0 0 14px" hidden></p>
        <input id="otpCode" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code"
          placeholder="123456"
          style="display:block;width:100%;height:52px;text-align:center;font-size:28px;letter-spacing:0.25em;font-weight:700;padding:0 14px;border:1px solid #E1D9D3;border-radius:12px;background:#fff;color:#211813;outline:none;box-sizing:border-box;margin-bottom:16px">
        <label style="display:flex;align-items:center;gap:10px;font-size:14px;color:#6D6159;margin-bottom:20px;cursor:pointer">
          <input id="otpRemember" type="checkbox" style="width:16px;height:16px;accent-color:#E8273A">
          Remember this device for 30 days
        </label>
        <div style="display:flex;flex-direction:column;gap:10px">
          <button id="otpVerify" class="btn primary" onclick="submitOTP()" style="height:46px">Verify</button>
          <button class="btn" onclick="document.getElementById('otpDlg').close()" style="height:40px">Cancel</button>
        </div>
      </dialog>
      ```

      Files: `web/auth.html`
      Verify: PowerShell `Select-String -Path 'web/auth.html' -Pattern 'needs_otp|showOTPStep|submitOTP'` — must return at least one match per pattern.

- [ ] 6. Modify `web/index.html` — Two-step verification section in Settings Security tab.

      **6a. Inject the 2FA section into the security tab's `body.innerHTML` template.**
      The current template at line 2134 ends with the Delete account section at line 2142:
      ```
      <button class="btn danger" data-act="delaccount">${ic("trash")}Delete my account</button></section>`;
      ```
      Insert a new section between the Password section (ending `</div></section>` after the Save/Forgot buttons) and the Sessions section. Specifically, in the template string, after the `</div></section>` that closes the Password section and before `<section class="set-sec"><h2>Sessions</h2>`, add:
      ```html
      <section class="set-sec" id="twofa_section">
        <h2>Two-step verification</h2>
        <p class="help">When enabled, signing in requires a code sent to your email after your password.</p>
        <div id="twofa_state"><span class="sub">Loading…</span></div>
      </section>
      ```

      **6b. After the `body.innerHTML = \`...\`` assignment in the security tab block**, add an async call to load the 2FA state. This goes immediately after the closing backtick-semicolon of the `body.innerHTML` assignment (line 2143), still inside the `if (tab === "security")` block:
      ```javascript
      // Load 2FA state asynchronously
      (async () => {
        const el = document.getElementById("twofa_state");
        if (!el) return;
        try {
          const st = await send("/api/auth/2fa/status", {});
          el.innerHTML = `<label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:15px">
            <input type="checkbox" id="twofa_toggle" ${st.enabled ? "checked" : ""} onchange="toggleTwoFA(this.checked)"
              style="width:17px;height:17px;accent-color:var(--brand)">
            <span>${st.enabled ? "Enabled" : "Disabled"}</span>
          </label>
          ${st.enabled ? `<p class="sub" style="margin-top:8px;color:#1a7a3a">✓ Two-step verification is on. You will be asked for a code on new devices.</p>` : ""}`;
        } catch (e) {
          el.innerHTML = `<span class="sub">${esc(e.message)}</span>`;
        }
      })();
      ```

      **6c. Add the `toggleTwoFA` global function.** Find the `async function drawSettings()` declaration (line 2101) and add the following function anywhere before it (e.g. right before it at line 2101):
      ```javascript
      async function toggleTwoFA(on) {
        const cb = document.getElementById("twofa_toggle");
        try {
          await send("/api/auth/2fa/toggle", {enabled: on});
          toast(on ? "Two-step verification enabled." : "Two-step verification disabled.", "ok");
          // Refresh the state div
          const el = document.getElementById("twofa_state");
          if (el) {
            el.innerHTML = `<span class="sub">Loading…</span>`;
            const st = await send("/api/auth/2fa/status", {});
            el.innerHTML = `<label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:15px">
              <input type="checkbox" id="twofa_toggle" ${st.enabled ? "checked" : ""} onchange="toggleTwoFA(this.checked)"
                style="width:17px;height:17px;accent-color:var(--brand)">
              <span>${st.enabled ? "Enabled" : "Disabled"}</span>
            </label>
            ${st.enabled ? `<p class="sub" style="margin-top:8px;color:#1a7a3a">✓ Two-step verification is on. You will be asked for a code on new devices.</p>` : ""}`;
          }
        } catch (err) {
          toast(err.message, "bad");
          // Revert the checkbox
          if (cb) cb.checked = !on;
        }
      }
      ```

      Files: `web/index.html`
      Verify: PowerShell `Select-String -Path 'web/index.html' -Pattern 'toggleTwoFA|twofa'` — must return matches.

- [ ] 7. Final verification pass — run all six checks from the spec.
      Run each of these in order from the repo root (`c:\Users\golur\Downloads\replix-main`):
      1. `python -c "import ast; ast.parse(open('studio/server.py').read()); print('server.py OK')"`
      2. `python -c "import ast; ast.parse(open('studio/email_otp.py').read()); print('email_otp.py OK')"`
      3. `python -c "import ast; ast.parse(open('studio/db.py').read()); print('db.py OK')"`
      4. `Select-String -Path 'web/auth.html' -Pattern 'needs_otp|showOTPStep|submitOTP'` — must have matches for all three patterns
      5. `Select-String -Path 'web/index.html' -Pattern 'toggleTwoFA|twofa'` — must have matches
      6. `Select-String -Path 'studio/db.py' -Pattern 'totp_settings|device_trusts'` — must have matches for both

      All six checks must pass before the work is considered complete.

---

## Design decisions

**In-memory OTP store keyed by `user_id`:** The existing `admin_otp.py` uses an email-keyed dict. For user 2FA the natural key is `user_id` (a stable `u_xxxx` string), which avoids the case of a user changing their email mid-flow. The same TTL+max-attempts pattern is preserved exactly.

**Upsert for `totp_settings` via delete-then-insert:** SQLite's `INSERT OR REPLACE` and PostgreSQL's `ON CONFLICT DO UPDATE` have different syntax. `auth.py` avoids this problem in `_make_link` by deleting the old row then inserting; the same approach is used here for portability.

**`trust_token` as a plain cookie + localStorage value:** The server stores only the SHA-256 hash (never the token), following the same pattern as session cookies in `auth.py`. The client stores the plain token in both localStorage (sent in the login POST body) and as a `replix_trust` cookie (HttpOnly, so unavailable to JS, used as a fallback). On the OTP verify route with `remember=True`, both are set.

**Graceful degradation when mailer is not configured:** If SMTP is not set up and the user has 2FA enabled, the login route skips the OTP step and signs them in directly. This prevents lockout during server migrations or misconfiguration.

**No `needs_otp` path for signup:** The signup flow creates a new session immediately; 2FA only applies to subsequent logins.
