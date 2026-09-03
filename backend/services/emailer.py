"""Email notifications via Resend (free tier: 100/day, no card needed).

Fire-and-forget: failures are logged, never raised — a missing/down email
service must never break a game turn.
"""
import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", "Cinematic Recall <onboarding@resend.dev>")


async def _send(to_email: str, subject: str, html: str) -> None:
    if not RESEND_API_KEY:
        return  # email not configured — silently skip
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={"from": EMAIL_FROM, "to": [to_email], "subject": subject, "html": html},
                timeout=10,
            )
    except Exception as e:
        print(f"[email] failed to send to {to_email}: {e}")


def send_email(to_email: str, subject: str, html: str) -> None:
    """Schedule an email without blocking the caller."""
    asyncio.create_task(_send(to_email, subject, html))


def _layout(title: str, body_html: str, cta_url: str | None = None,
            cta_label: str = "Open Cinematic Recall") -> str:
    cta = ""
    if cta_url:
        cta = (f'<a href="{cta_url}" style="display:inline-block;background:#16a34a;color:#fff;'
               f'padding:12px 28px;border-radius:10px;text-decoration:none;font-weight:700;margin-top:16px">'
               f'{cta_label}</a>')
    return f"""<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px;margin:0 auto;
              background:#16213e;border-radius:16px;padding:32px;color:#fff;text-align:center">
      <h2 style="margin:0 0 8px">🎬 {title}</h2>
      <p style="color:#cbd5e1;line-height:1.6">{body_html}</p>
      {cta}
      <p style="color:#64748b;font-size:.8rem;margin-top:24px">Cinematic Recall</p>
    </div>"""


def email_turn_assigned(to_email: str, player_name: str, actor_name: str,
                        namer_name: str | None = None, namer_movie: str | None = None,
                        match_url: str | None = None):
    last = f"{namer_name} just claimed “{namer_movie}”!" if namer_movie else "The match is waiting for you."
    send_email(
        to_email,
        f"🎬 Your turn — {actor_name}",
        _layout(
            "Your turn!",
            f"Hi {player_name} — it's your turn to name a movie by <b>{actor_name}</b>.<br>{last}<br>"
            "Take your time: the 2-minute clock only starts when you press Start.",
            match_url,
            "Play my turn",
        ),
    )


def email_invite(to_email: str, inviter_name: str, invite_url: str):
    send_email(
        to_email,
        f"🎬 {inviter_name} challenged you to Cinematic Recall",
        _layout(
            "You're invited!",
            f"<b>{inviter_name}</b> started a match and wants you in.<br>"
            "Create your account (one time only) and you'll be in every game.",
            invite_url,
            "Join the match",
        ),
    )
