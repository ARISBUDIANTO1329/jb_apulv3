"""
Google Token Service - Auto-refresh + save to DB.
Based on v2 GoogleChannelTokenService pattern.
Fixed: use creds.refresh() without httplib2
"""

import os
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("google_token_service")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _build_credentials(channel):
    """Build Google OAuth2 credentials from channel tokens."""
    from google.oauth2.credentials import Credentials
    return Credentials(
        token=channel.access_token,
        refresh_token=channel.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )


def _save_refreshed_tokens(channel, creds):
    """Save refreshed tokens back to channel model (no commit)."""
    channel.access_token = creds.token
    if creds.refresh_token:
        channel.refresh_token = creds.refresh_token
    if creds.expiry:
        channel.token_expires_at = creds.expiry
    else:
        channel.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    channel.token_status = "valid"
    channel.token_error = None
    channel.token_checked_at = datetime.now(timezone.utc)


async def get_youtube_client(channel, db):
    """Get authenticated YouTube Data API client with auto-refresh + DB save."""
    from googleapiclient.discovery import build
    from fastapi import HTTPException

    if not channel.access_token and not channel.refresh_token:
        raise HTTPException(status_code=400, detail="Channel not connected to Google.")

    creds = _build_credentials(channel)

    if creds.expired and creds.refresh_token:
        try:
            log.info(f"Refreshing token for channel {channel.id}")
            creds.refresh()
            _save_refreshed_tokens(channel, creds)
            await db.commit()
            await db.refresh(channel)
            log.info(f"Token refreshed for channel {channel.id}")
        except Exception as e:
            log.error(f"Token refresh failed for channel {channel.id}: {e}")
            channel.token_status = "error"
            channel.token_error = str(e)
            channel.token_checked_at = datetime.now(timezone.utc)
            await db.commit()
            raise HTTPException(status_code=401, detail=f"Token refresh failed: {e}. Please reconnect Google.")

    return build("youtube", "v3", credentials=creds), creds


async def get_analytics_client(channel, db):
    """Get authenticated YouTube Analytics API client with auto-refresh + DB save."""
    from googleapiclient.discovery import build
    from fastapi import HTTPException

    if not channel.access_token and not channel.refresh_token:
        raise HTTPException(status_code=400, detail="Channel not connected to Google.")

    creds = _build_credentials(channel)

    if creds.expired and creds.refresh_token:
        try:
            log.info(f"Refreshing token for channel {channel.id}")
            creds.refresh()
            _save_refreshed_tokens(channel, creds)
            await db.commit()
            await db.refresh(channel)
            log.info(f"Token refreshed for channel {channel.id}")
        except Exception as e:
            log.error(f"Token refresh failed for channel {channel.id}: {e}")
            channel.token_status = "error"
            channel.token_error = str(e)
            channel.token_checked_at = datetime.now(timezone.utc)
            await db.commit()
            raise HTTPException(status_code=401, detail=f"Token refresh failed: {e}. Please reconnect Google.")

    return build("youtubeAnalytics", "v2", credentials=creds), creds


async def try_refresh_token(channel, db):
    """Try to refresh an expired token. Returns (success, message)."""
    if not channel.refresh_token:
        return False, "No refresh token available. Please reconnect Google."

    try:
        import time
        creds = _build_credentials(channel)
        last_error = ""
        for attempt in range(2):
            try:
                creds.refresh()
                break
            except Exception as e:
                last_error = str(e)
                if attempt == 0:
                    time.sleep(0.5)  # 500ms delay before retry (like v2)
                else:
                    raise
        _save_refreshed_tokens(channel, creds)
        await db.commit()
        await db.refresh(channel)
        log.info(f"Token auto-refreshed for channel {channel.id}")
        return True, "Token refreshed successfully"
    except Exception as e:
        msg = str(e) or last_error
        log.error(f"Token refresh failed for channel {channel.id}: {msg}")
        channel.token_status = "error"
        channel.token_error = msg
        channel.token_checked_at = datetime.now(timezone.utc)
        await db.commit()
        return False, f"Refresh failed: {msg}"