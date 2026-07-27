#!/usr/bin/env python3
"""
Token Refresh Script - Run via cron to keep OAuth tokens fresh.
Usage: */30 * * * * cd /var/www/jb_apulv3 && python3 scripts/refresh_tokens.py
"""

import os
import sys
import requests
from datetime import datetime

# Backend URL
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")

def refresh_tokens():
    """Refresh tokens for all channels."""
    print(f"[{datetime.now()}] Starting token refresh...")

    try:
        # Get all channels
        resp = requests.get(f"{BACKEND_URL}/api/channels", timeout=10)
        channels = resp.json()

        for channel in channels:
            channel_id = channel["id"]
            channel_name = channel["name"]

            try:
                # Check and refresh token
                resp = requests.post(
                    f"{BACKEND_URL}/api/livestream/check-token",
                    params={"channel_id": channel_id},
                    timeout=30
                )
                data = resp.json()

                if data.get("valid"):
                    print(f"  ✅ {channel_name}: {data.get('message')}")
                else:
                    print(f"  ❌ {channel_name}: {data.get('message')}")

            except Exception as e:
                print(f"  ❌ {channel_name}: Error - {e}")

    except Exception as e:
        print(f"❌ Failed to get channels: {e}")
        return False

    print(f"[{datetime.now()}] Token refresh completed")
    return True


if __name__ == "__main__":
    success = refresh_tokens()
    sys.exit(0 if success else 1)
