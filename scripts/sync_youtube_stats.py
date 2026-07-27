#!/usr/bin/env python3
"""
Sync YouTube channel stats (subscribers, views, videos)
Run this script periodically to update channel statistics.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import httplib2

# Config
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jb_user:change-me@db:5432/jb_apulv3")
DB_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

def get_db():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def get_channel_stats(youtube):
    """Get channel statistics from YouTube API."""
    try:
        response = youtube.channels().list(
            part="statistics",
            mine=True
        ).execute()
        
        if response.get("items"):
            stats = response["items"][0]["statistics"]
            return {
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "hidden_subs": stats.get("hiddenSubscriberCount", False),
            }
    except Exception as e:
        print(f"Error getting stats: {e}")
    return None

def main():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Get all channels with valid tokens
            cur.execute("SELECT id, name, youtube_channel_id, access_token, refresh_token FROM channels WHERE access_token IS NOT NULL")
            channels = cur.fetchall()
            
            print(f"Found {len(channels)} channels with tokens")
            
            for ch in channels:
                channel_id = ch["id"]
                channel_name = ch["name"]
                
                print(f"\nSyncing: {channel_name} (ID: {channel_id})")
                
                # Build credentials
                creds = Credentials(
                    token=ch["access_token"],
                    refresh_token=ch["refresh_token"],
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
                    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                )
                
                # Refresh if expired
                if creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(httplib2.Http())
                        cur.execute("UPDATE channels SET access_token=%s WHERE id=%s", (creds.token, channel_id))
                        conn.commit()
                        print("  Token refreshed")
                    except Exception as e:
                        print(f"  Token refresh failed: {e}")
                        continue
                
                # Build YouTube service
                youtube = build("youtube", "v3", credentials=creds)
                
                # Get stats
                stats = get_channel_stats(youtube)
                
                if stats:
                    # Update database
                    cur.execute("""
                        UPDATE channels 
                        SET subscriber_count = %s, 
                            total_views = %s, 
                            video_count = %s,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (
                        stats["subscriber_count"],
                        stats["total_views"],
                        stats["video_count"],
                        channel_id
                    ))
                    conn.commit()
                    
                    print(f"  Subscribers: {stats['subscriber_count']:,}")
                    print(f"  Total Views: {stats['total_views']:,}")
                    print(f"  Videos: {stats['video_count']:,}")
                    if stats["hidden_subs"]:
                        print("  ⚠️ Subscriber count is hidden")
                else:
                    print("  ❌ Failed to get stats")
            
            print("\n✅ Sync completed!")
            
    finally:
        conn.close()

if __name__ == "__main__":
    main()
