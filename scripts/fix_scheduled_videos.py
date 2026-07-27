#!/usr/bin/env python3
"""
Fix scheduled videos that were uploaded without publishAt.
Updates YouTube video status to scheduled with proper publishAt time.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import httplib2

# Config
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jb_user:change-me@db:5432/jb_apulv3")
DB_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

def get_db():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def get_channel(channel_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM channels WHERE id=%s", (channel_id,))
            return cur.fetchone()
    finally:
        conn.close()

def update_youtube_video(youtube, video_id, publish_at):
    """Update YouTube video to scheduled status."""
    try:
        # First get current video details
        video_response = youtube.videos().list(
            part="snippet,status",
            id=video_id
        ).execute()
        
        if not video_response.get("items"):
            print(f"Video {video_id} not found")
            return False
        
        video = video_response["items"][0]
        snippet = video["snippet"]
        status = video["status"]
        
        # Update to scheduled
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.isoformat()
        
        update_response = youtube.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": status
            }
        ).execute()
        
        print(f"Updated {video_id}: scheduled for {publish_at}")
        return True
        
    except Exception as e:
        print(f"Error updating {video_id}: {e}")
        return False

def main():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Get scheduled items that need fixing
            cur.execute("""
                SELECT ubi.*, ub.channel_id 
                FROM upload_batch_items ubi
                JOIN upload_batches ub ON ubi.upload_batch_id = ub.id
                WHERE ubi.visibility = 'scheduled' 
                AND ubi.status = 'done'
                AND ubi.youtube_video_id IS NOT NULL
                AND ubi.youtube_video_id != ''
                ORDER BY ubi.id
            """)
            items = cur.fetchall()
            
            print(f"Found {len(items)} scheduled videos to fix")
            
            for item in items:
                video_id = item["youtube_video_id"]
                channel_id = item["channel_id"]
                scheduled_at = item.get("scheduled_at")
                
                if not scheduled_at:
                    print(f"Skipping {item['id']}: no scheduled_at")
                    continue
                
                # Get channel credentials
                channel = get_channel(channel_id)
                if not channel:
                    print(f"Skipping {item['id']}: channel not found")
                    continue
                
                # Build credentials
                creds = Credentials(
                    token=channel["access_token"],
                    refresh_token=channel["refresh_token"],
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
                    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                )
                
                # Refresh if needed
                if creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(httplib2.Http())
                        # Update token in DB
                        cur.execute("UPDATE channels SET access_token=%s WHERE id=%s", 
                                   (creds.token, channel_id))
                        conn.commit()
                    except Exception as e:
                        print(f"Token refresh failed for channel {channel_id}: {e}")
                        continue
                
                # Build YouTube service
                youtube = build("youtube", "v3", credentials=creds)
                
                # Update video
                success = update_youtube_video(youtube, video_id, scheduled_at)
                
                if success:
                    print(f"✅ Fixed: {item['title'][:50]}...")
                else:
                    print(f"❌ Failed: {item['title'][:50]}...")
                
    finally:
        conn.close()

if __name__ == "__main__":
    main()
