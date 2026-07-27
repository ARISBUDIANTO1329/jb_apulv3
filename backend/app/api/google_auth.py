"""
Google OAuth - Connect YouTube channel to Google account.
User opens URL in local browser, VPS receives callback with tokens.
"""

import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta

from app.db.session import get_db
from app.models.channel import Channel

router = APIRouter()

# Google OAuth config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "https://jb1.apul.my.id/api/auth/google/callback")

SCOPES = [
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


@router.get("/connect/{channel_id}")
async def google_connect(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Generate Google OAuth URL for a channel."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")

    # Build OAuth URL
    scopes_str = "%20".join(SCOPES)
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope={scopes_str}&"
        f"access_type=offline&"
        f"prompt=consent&"
        f"state={channel_id}"
    )

    return {
        "success": True,
        "auth_url": auth_url,
        "channel_id": channel_id,
        "channel_name": channel.name,
    }


@router.get("/connect-redirect/{channel_id}")
async def google_connect_redirect(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Redirect directly to Google OAuth page."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")

    # Build OAuth URL
    scopes_str = "%20".join(SCOPES)
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope={scopes_str}&"
        f"access_type=offline&"
        f"prompt=consent&"
        f"state={channel_id}"
    )

    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def google_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback."""
    if error:
        return HTMLResponse(f"""
            <html><body style='font-family:Inter,sans-serif;padding:40px;text-align:center;'>
            <h2>❌ OAuth Error</h2>
            <p>{error}</p>
            <a href='/'>← Kembali</a>
            </body></html>
        """)

    if not code:
        return HTMLResponse("<html><body>Missing code parameter</body></html>")

    channel_id = int(state) if state else None
    if not channel_id:
        return HTMLResponse("<html><body>Missing channel state</body></html>")

    # Exchange code for tokens
    import httpx
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        return HTMLResponse(f"""
            <html><body style='font-family:Inter,sans-serif;padding:40px;text-align:center;'>
            <h2>❌ Token Exchange Gagal</h2>
            <p>{token_resp.text}</p>
            <a href='/'>← Kembali</a>
            </body></html>
        """)

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        return HTMLResponse("<html><body>Access token kosong</body></html>")

    # Get Google user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    google_email = ""
    if user_resp.status_code == 200:
        user_data = user_resp.json()
        google_email = user_data.get("email", "")

    # Update channel in database
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        return HTMLResponse("<html><body>Channel tidak ditemukan</body></html>")

    channel.access_token = access_token
    channel.refresh_token = refresh_token or channel.refresh_token
    channel.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    channel.email = google_email
    await db.commit()

    # Success page
    return HTMLResponse(f"""
        <html><body style='font-family:Inter,sans-serif;padding:40px;text-align:center;'>
        <h2>✅ Google Berhasil Dikoneksikan!</h2>
        <p>Channel: <strong>{channel.name}</strong></p>
        <p>Email: <strong>{google_email}</strong></p>
        <p>Token berlaku selama {expires_in // 3600} jam</p>
        <br>
        <p style='color:#666;'>Anda bisa menutup halaman ini dan kembali ke JB Channel Manager.</p>
        <a href='/' style='display:inline-block;margin-top:20px;padding:10px 20px;background:#2563eb;color:white;text-decoration:none;border-radius:8px;'>← Kembali ke Dashboard</a>
        </body></html>
    """)


@router.get("/status/{channel_id}")
async def google_status(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Check Google OAuth status for a channel."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel tidak ditemukan")

    has_token = bool(channel.access_token)
    expires_at = channel.token_expires_at
    is_expired = expires_at and expires_at < datetime.now(timezone.utc) if expires_at else True

    return {
        "connected": has_token and not is_expired,
        "google_email": channel.email or "",
        "expires_at": expires_at.isoformat() if expires_at else None,
        "is_expired": is_expired,
    }
