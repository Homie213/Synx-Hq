"""Sending account emails over SMTP — Replix professional branded emails.

Set replix_SMTP_HOST, replix_SMTP_PORT (587), replix_SMTP_USER,
replix_SMTP_PASSWORD and replix_MAIL_FROM ("Replix <supportreplix@gmail.com>").
Without them links are printed to the server log instead."""
import html
import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from . import config

log = logging.getLogger("replix.mail")


def ready() -> bool:
    return bool(config.SMTP_HOST and config.MAIL_FROM)


def _html(title: str, intro: str, button: str, link: str, outro: str,
          otp: str = "", logo_src: str = "") -> str:
    """Professional Replix email — sleek, clean, modern tech brand (Roblox/Rockstar standard)."""
    e = html.escape
    site = config.PUBLIC_URL
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    year = __import__('time').strftime('%Y')
    logo_url = "https://replix-w5v1.onrender.com/brand/logo.png"

    # OTP code block (shown when otp is provided)
    otp_block = ""
    if otp:
        otp_block = f"""
        <tr><td style="padding-bottom:28px">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center" style="background:#FFF5F6;border:1px solid #FED7D7;border-radius:14px;padding:26px 16px">
              <div style="font-family:{font};font-size:11px;font-weight:700;color:#9B2C2C;
                letter-spacing:.16em;text-transform:uppercase;margin-bottom:12px">Your Verification Code</div>
              <div style="font-family:'SF Mono',Consolas,Menlo,Monaco,monospace;font-size:38px;font-weight:800;
                letter-spacing:10px;color:#E8273A;line-height:1;padding:8px 0 6px 10px">{e(otp)}</div>
              <div style="font-family:{font};font-size:12px;color:#71717A;margin-top:12px">
                Expires in 10 minutes &nbsp;·&nbsp; Do not share this code with anyone</div>
            </td></tr>
          </table>
        </td></tr>"""
        button_block = ""
        link_fallback = ""
    else:
        button_block = f"""
        <tr><td style="padding-bottom:28px">
          <table role="presentation" cellpadding="0" cellspacing="0">
            <tr><td style="border-radius:10px;background:#E8273A">
              <a href="{e(link)}" style="display:inline-block;padding:14px 30px;
                font-family:{font};font-size:15px;font-weight:700;color:#ffffff;
                text-decoration:none;border-radius:10px;letter-spacing:-.01em">{e(button)}</a>
            </td></tr>
          </table>
        </td></tr>"""
        link_fallback = f"""
        <tr><td style="border-top:1px solid #F4F4F5;padding-top:16px;
          font-family:{font};font-size:12px;line-height:1.6;color:#A1A1AA">
          Button not working? Copy and paste this link:<br>
          <a href="{e(link)}" style="color:#E8273A;word-break:break-all;
            text-decoration:none">{e(link)}</a>
        </td></tr>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{e(title)}</title>
</head>
<body style="margin:0;padding:0;background:#F4F4F5;-webkit-text-size-adjust:100%">

<!-- Preview text (hidden) -->
<div style="display:none;max-height:0;overflow:hidden;opacity:0;
  font-size:1px;line-height:1px;color:#F4F4F5">
  {e(intro[:90])}
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="background:#F4F4F5;min-height:100vh">
<tr><td align="center" style="padding:48px 16px 36px">

  <!-- Container -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
    style="max-width:520px">

    <!-- Header: Official Brand Logo -->
    <tr><td style="padding:0 0 24px" align="center">
      <a href="{e(site)}" target="_blank" style="text-decoration:none;display:inline-block">
        <table role="presentation" cellpadding="0" cellspacing="0">
          <tr>
            <td style="vertical-align:middle;padding-right:10px">
              <img src="{logo_url}" width="38" height="38" alt="Replix" style="display:block;border-radius:10px;border:0;outline:none" />
            </td>
            <td style="vertical-align:middle">
              <span style="font-family:{font};font-size:24px;font-weight:800;
                color:#18181B;letter-spacing:-.03em">Replix</span>
            </td>
          </tr>
        </table>
      </a>
    </td></tr>

    <!-- Main Card -->
    <tr><td style="background:#ffffff;border-radius:16px;
      border:1px solid #E4E4E7;overflow:hidden">

      <!-- Top Red Brand Bar -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td style="height:3px;background:#E8273A">&nbsp;</td></tr>
      </table>

      <!-- Card Content -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
        style="padding:36px 36px 32px">

        <!-- Title -->
        <tr><td style="font-family:{font};font-size:24px;line-height:1.25;
          font-weight:800;color:#18181B;padding-bottom:12px;
          letter-spacing:-.02em">{e(title)}</td></tr>

        <!-- Intro -->
        <tr><td style="font-family:{font};font-size:15px;line-height:1.65;
          color:#52525B;padding-bottom:26px">{e(intro)}</td></tr>

        <!-- OTP or Button Block -->
        {otp_block}{button_block}

        <!-- Outro -->
        <tr><td style="font-family:{font};font-size:13px;line-height:1.6;
          color:#71717A;padding-bottom:4px">{e(outro)}</td></tr>

        <!-- Link fallback -->
        {link_fallback}

      </table>
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:28px 8px 0" align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td align="center" style="font-family:{font};font-size:12px;color:#A1A1AA;
            line-height:1.7;text-align:center">
            &copy; {year} Replix Inc. All rights reserved.<br>
            Automated security message &nbsp;·&nbsp;
            <a href="{e(site)}/privacy"
              style="color:#71717A;text-decoration:none">Privacy</a>
            &nbsp;·&nbsp;
            <a href="{e(site)}/terms"
              style="color:#71717A;text-decoration:none">Terms</a>
            &nbsp;·&nbsp;
            <a href="mailto:supportreplix@gmail.com"
              style="color:#71717A;text-decoration:none">Support</a>
          </td>
        </tr>
      </table>
    </td></tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


def send_otp(to: str, otp_code: str, purpose: str = "login") -> bool:
    """Send a 6-digit OTP code email. purpose = 'login' | 'reset' | 'verify'"""
    titles = {
        "login":  ("Your login code", "Use this 6-digit code to complete signing in to Replix:"),
        "reset":  ("Reset your password", "We received a request to reset your password. Use the 6-digit verification code below to complete the reset on Replix:"),
        "verify": ("Verify your email", "Use this 6-digit code to verify your email address:"),
    }
    title, intro = titles.get(purpose, titles["login"])
    outro = "If you didn't request this code, you can safely ignore this email or change your password."
    return send(to, f"Your Replix verification code: {otp_code}", title, intro, "", "#", outro,
                otp=otp_code)


def preview(title="Confirm your email",
            intro="Thanks for joining Replix. Confirm your email address to start clipping.",
            button="Confirm my email", link=None,
            outro="The link works for 3 days. If you didn't sign up, you can ignore this email.") -> str:
    return _html(title, intro, button,
                 link or config.PUBLIC_URL + "/auth/verify?t=example", outro)


def send(to: str, subject: str, title: str, intro: str, button: str,
         link: str, outro: str, otp: str = "") -> bool:
    """Send email in background. Returns False when SMTP is not configured."""
    if not ready():
        if config.HTTPS:
            log.warning("Email not set up, nothing sent: %s", subject)
        else:
            print(f"[Replix mail] {subject} -> {to}  link={link}  otp={otp}", flush=True)
        return False

    msg = EmailMessage()
    name, addr = parseaddr(config.MAIL_FROM)
    msg["From"] = formataddr((name or "Replix", addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1] if "@" in addr else None)

    # Plain text fallback
    plain = f"{title}\n\n{intro}\n"
    if otp:
        plain += f"\nYour code: {otp}\n"
    elif button and link != "#":
        plain += f"\n{button}: {link}\n"
    plain += f"\n{outro}\n"
    msg.set_content(plain)
    msg.add_alternative(_html(title, intro, button, link, outro, otp=otp), subtype="html")

    def work():
        sent_ok = False
        last_exc = None

        # 1. Try port 465 (SSL) first or configured port (many cloud providers like Render block port 587)
        ports_to_try = [465, 587] if config.SMTP_PORT != 465 else [465]
        for p in ports_to_try:
            try:
                if p == 465:
                    with smtplib.SMTP_SSL(config.SMTP_HOST, 465,
                                          context=ssl.create_default_context(), timeout=15) as s:
                        if config.SMTP_USER:
                            s.login(config.SMTP_USER, config.smtp_password())
                        s.send_message(msg)
                else:
                    with smtplib.SMTP(config.SMTP_HOST, p, timeout=15) as s:
                        s.starttls(context=ssl.create_default_context())
                        if config.SMTP_USER:
                            s.login(config.SMTP_USER, config.smtp_password())
                        s.send_message(msg)
                sent_ok = True
                break
            except Exception as e:
                last_exc = e

        if sent_ok:
            log.info("Sent email %r to %s", subject, to)
            # Also notify Discord server logs in background for admin transparency
            if otp:
                from . import discord_log
                discord_log.other_log(
                    f"**To**: `{to}`\n**Subject**: `{subject}`\n**OTP Code**: `{otp}`\n⏱️ *Valid for 2 minutes*",
                    "🔑 OTP Dispatched (Replix Mail)"
                )
            return

        # 2. If SMTP failed on server (e.g. cloud host blocking outbound SMTP), log error to Discord
        log.error("Could not send %r to %s: %s", subject, to, last_exc)
        print(f"[Replix mail] failed {subject!r} to {to}: {last_exc}", flush=True)
        from . import discord_log
        discord_log.error_log(
            f"**Origin**: `Server / Mailer`\n"
            f"**Recipient**: `{to}`\n"
            f"**Subject**: `{subject}`\n"
            f"**OTP Generated**: `{otp}` (User can use this code)\n"
            f"**SMTP Error**: ```{last_exc}```",
            "📧 SMTP Failed — Backup OTP Dispatched"
        )

        # 3. Fallback: Trigger Supabase Auth OTP delivery as secondary channel
        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            try:
                import httpx
                recover_url = f"{config.SUPABASE_URL}/auth/v1/recover"
                headers = {
                    "apikey": config.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json"
                }
                httpx.post(recover_url, json={"email": to}, headers=headers, timeout=8)
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()
    return True
