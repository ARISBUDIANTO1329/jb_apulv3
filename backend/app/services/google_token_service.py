"""
Google Token Service - Handle OAuth token refresh and management.
Auto-refresh expired tokens and save to database.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import httplib2

log = logging.getLogger("google_token_service")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


class GoogleTokenService:
    """Service for managing Google OAuth tokens with auto-refresh."""

    @staticmethod
    async def get_youtube_client(channel, db: AsyncSession):
        """
        Get authenticated YouTube Data API client.
        Auto-refreshes token if expired and saves to DB.
        
        Returns: (youtube_service, credentials)
        """
        if not channel.access_token:
            raise Exception("Channel not connected to Google. Please connect first.")

        creds = Credentials(
            token=channel.access_token,
            refresh_token=channel.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )

        # Check if token expired and refresh
        if creds.expired and creds.refresh_token:
            try:
                log.info(f"Token expired for channel {channel.id}, refreshing...")
                creds.refresh(httplib2.Http())
                
                # Save new token to database
                channel.access_token = creds.token
                if creds.refresh_token:  # Sometimes refresh returns new refresh_token
                    channel.refresh_token = creds.refresh_token
                
                # Calculate and save expiry time
                if creds.expiry:
                    channel.token_expires_at = creds.expiry
                else:
                    # Default 1 hour if not provided
                    channel.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
                
                channel.token_status = "valid"
                channel.token_error = None
                channel.token_checked_at = datetime.now(timezone.utc)
                
                await db.commit()
                await db.refresh(channel)
                
                log.info(f"Token refreshed and saved for channel {channel.id}")
                
            except Exception as e:
                log.error(f"Token refresh failed for channel {channel.id}: {e}")
                channel.token_status = "expired"
                channel.token_error = str(e)
                channel.token_checked_at = datetime.now(timezone.utc)
                await db.commit()
                
                raise Exception(f"Token refresh failed: {e}. Please reconnect Google.")

        # Build and return YouTube service
        youtube = build("youtube", "v3", credentials=creds)
        return youtube, creds

    @staticmethod
    async def get_analytics_client(channel, db: AsyncSession):
        """
        Get authenticated YouTube Analytics API client.
        Auto-refreshes token if expired and saves to DB.
        
        Returns: (analytics_service, credentials)
        """
        if not channel.access_token:
            raise Exception("Channel not connected to Google. Please connect first.")

        creds = Credentials(
            token=channel.access_token,
            refresh_token=channel.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )

        # Check if token expired and refresh
        if creds.expired and creds.refresh_token:
            try:
                log.info(f"Token expired for channel {channel.id}, refreshing...")
                creds.refresh(httplib2.Http())
                
                # Save new token to database
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
                
                await db.commit()
                await db.refresh(channel)
                
                log.info(f"Token refreshed and saved for channel {channel.id}")
                
            except Exception as e:
                log.error(f"Token refresh failed for channel {channel.id}: {e}")
                channel.token_status = "expired"
                channel.token_error = str(e)
                channel.token_checked_at = datetime.now(timezone.utc)
                await db.commit()
                
                raise Exception(f"Token refresh failed: {e}. Please reconnect Google.")

        # Build and return Analytics service
        analytics = build("youtubeAnalytics", "v2", credentials=creds)
        return analytics, creds

    @staticmethod
    async def validate_token(channel, db: AsyncSession) -> Dict[str, Any]:
        """
        Validate token and attempt refresh if expired.
        Returns status info without making API calls.
        
        Returns: {
            "valid": bool,
            "message": str,
            "expires_at": datetime or None,
            "expires_in_hours": int or None
        }
        """
        if not channel.access_token:
            return {
                "valid": False,
                "message": "Not connected. Please connect Google account.",
                "expires_at": None,
                "expires_in_hours": None
            }

        # Check expiry
        if channel.token_expires_at:
            now = datetime.now(timezone.utc)
            expires_in = (channel.token_expires_at - now).total_seconds() / 3600
            
            if expires_in > 0.5:  # More than 30 minutes remaining
                return {
                    "valid": True,
                    "message": f"Token valid, expires in {int(expires_in)} hours",
                    "expires_at": channel.token_expires_at,
                    "expires_in_hours": int(expires_in)
                }
        
        # Token expired or about to expire, try refresh
        if channel.refresh_token:
            try:
                creds = Credentials(
                    token=channel.access_token,
                    refresh_token=channel.refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=GOOGLE_CLIENT_ID,
                    client_secret=GOOGLE_CLIENT_SECRET,
                )
                
                creds.refresh(httplib2.Http())
                
                # Save refreshed token
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
                
                await db.commit()
                await db.refresh(channel)
                
                expires_in = (channel.token_expires_at - datetime.now(timezone.utc)).total_seconds() / 3600
                
                return {
                    "valid": True,
                    "message": "Token refreshed successfully",
                    "expires_at": channel.token_expires_at,
                    "expires_in_hours": int(expires_in)
                }
                
            except Exception as e:
                log.error(f"Token validation/refresh failed: {e}")
                channel.token_status = "expired"
                channel.token_error = str(e)
                channel.token_checked_at = datetime.now(timezone.utc)
                await db.commit()
                
                return {
                    "valid": False,
                    "message": f"Token expired and refresh failed: {e}",
                    "expires_at": channel.token_expires_at,
                    "expires_in_hours": None
                }
        else:
            return {
                "valid": False,
                "message": "Token expired and no refresh token available. Please reconnect.",
                "expires_at": channel.token_expires_at,
                "expires_in_hours": None
            }

    @staticmethod
    def get_token_status(channel) -> Dict[str, Any]:
        """
        Get current token status for UI display.
        Does NOT make any API calls or refresh attempts.
        
        Returns: {
            "connected": bool,
            "email": str,
            "expires_at": datetime or None,
            "expires_in_hours": int or None,
            "status": 'valid'|'expired'|'not_connected',
            "status_message": str
        }
        """
        if not channel.access_token:
            return {
                "connected": False,
                "email": channel.email or "",
                "expires_at": None,
                "expires_in_hours": None,
                "status": "not_connected",
                "status_message": "Not connected"
            }
        
        # Check expiry
        if channel.token_expires_at:
            now = datetime.now(timezone.utc)
            expires_in = (channel.token_expires_at - now).total_seconds() / 3600
            
            if expires_in > 0:
                return {
                    "connected": True,
                    "email": channel.email or "",
                    "expires_at": channel.token_expires_at,
                    "expires_in_hours": int(expires_in) if expires_in > 1 else 0,
                    "status": "valid",
                    "status_message": f"Connected, expires in {int(expires_in)}h" if expires_in > 1 else "Connected, expires soon"
                }
            else:
                return {
                    "connected": True,
                    "email": channel.email or "",
                    "expires_at": channel.token_expires_at,
                    "expires_in_hours": 0,
                    "status": "expired",
                    "status_message": "Token expired, needs reconnect"
                }
        else:
            # Has token but no expiry info
            return {
                "connected": True,
                "email": channel.email or "",
                "expires_at": None,
                "expires_in_hours": None,
                "status": "valid",
                "status_message": "Connected"
            }
