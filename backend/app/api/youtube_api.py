"""
YouTube API — JB APUL v3
List videos, pull stats, pull analytics data.
Uses existing OAuth tokens from channels table.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.db.session import get_db
from app.models.channel import Channel

router = APIRouter()
log = logging.getLogger("youtube_api")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _get_youtube_service(channel):
    """Build authenticated YouTube Data API service."""
    import httplib2
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials

    if not channel.access_token:
        raise HTTPException(status_code=400, detail="Channel not connected to YouTube. Please re-authorize.")

    creds = Credentials(
        token=channel.access_token,
        refresh_token=channel.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(httplib2.Http())
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Token refresh failed: {e}")

    return build("youtube", "v3", credentials=creds), creds


def _get_analytics_service(channel):
    """Build authenticated YouTube Analytics API service."""
    import httplib2
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials

    if not channel.access_token:
        raise HTTPException(status_code=400, detail="Channel not connected to YouTube.")

    creds = Credentials(
        token=channel.access_token,
        refresh_token=channel.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(httplib2.Http())
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Token refresh failed: {e}")

    return build("youtubeAnalytics", "v2", credentials=creds), creds


# ── List Videos ───────────────────────────────────────────────

@router.get("/videos/{channel_id}")
async def list_videos(channel_id: int, max_results: int = 50, db: AsyncSession = Depends(get_db)):
    """
    List all videos for a channel with basic stats.
    Uses YouTube Data API v3: search.list + videos.list
    """
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    youtube, creds = _get_youtube_service(channel)

    try:
        # Step 1: Get channel's upload playlist
        ch_response = youtube.channels().list(
            part="contentDetails,statistics",
            mine=True,
        ).execute()

        if not ch_response.get("items"):
            # Try by channel ID
            if channel.youtube_channel_id:
                ch_response = youtube.channels().list(
                    part="contentDetails,statistics",
                    id=channel.youtube_channel_id,
                ).execute()

        if not ch_response.get("items"):
            return {"success": False, "error": "Channel not found on YouTube", "videos": []}

        uploads_playlist = ch_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ch_stats = ch_response["items"][0].get("statistics", {})

        # Step 2: Get videos from uploads playlist
        videos = []
        next_page = None
        fetched = 0

        while fetched < max_results:
            batch_size = min(50, max_results - fetched)
            pl_response = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=uploads_playlist,
                maxResults=batch_size,
                pageToken=next_page,
            ).execute()

            video_ids = []
            for item in pl_response.get("items", []):
                vid = item["contentDetails"]["videoId"]
                video_ids.append(vid)

            if video_ids:
                # Step 3: Get video stats
                stats_response = youtube.videos().list(
                    part="statistics,snippet,contentDetails",
                    id=",".join(video_ids),
                ).execute()

                for v in stats_response.get("items", []):
                    snippet = v.get("snippet", {})
                    statistics = v.get("statistics", {})
                    content = v.get("contentDetails", {})

                    videos.append({
                        "video_id": v["id"],
                        "title": snippet.get("title", ""),
                        "description": snippet.get("description", "")[:200],
                        "published_at": snippet.get("publishedAt", ""),
                        "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                        "tags": snippet.get("tags", []),
                        "category_id": snippet.get("categoryId", ""),
                        "duration": content.get("duration", ""),
                        "view_count": int(statistics.get("viewCount", 0)),
                        "like_count": int(statistics.get("likeCount", 0)),
                        "comment_count": int(statistics.get("commentCount", 0)),
                        "youtube_url": f"https://youtube.com/watch?v={v['id']}",
                    })

            fetched += len(pl_response.get("items", []))
            next_page = pl_response.get("nextPageToken")
            if not next_page:
                break

        # Save updated token if refreshed
        if creds.token != channel.access_token:
            channel.access_token = creds.token
            await db.commit()

        return {
            "success": True,
            "channel": channel.name,
            "channel_id": channel_id,
            "channel_stats": {
                "subscribers": int(ch_stats.get("subscriberCount", 0)),
                "total_views": int(ch_stats.get("viewCount", 0)),
                "total_videos": int(ch_stats.get("videoCount", 0)),
            },
            "video_count": len(videos),
            "videos": videos,
        }

    except Exception as e:
        log.error(f"YouTube API error: {e}")
        if "quotaExceeded" in str(e):
            raise HTTPException(status_code=429, detail="YouTube API quota exceeded. Try again tomorrow.")
        if "invalid_grant" in str(e) or "unauthorized" in str(e).lower():
            raise HTTPException(status_code=401, detail="YouTube token expired. Please re-authorize channel.")
        raise HTTPException(status_code=500, detail=f"YouTube API error: {str(e)[:200]}")


# ── Video Stats (single video) ───────────────────────────────

@router.get("/video-stats/{channel_id}/{video_id}")
async def video_stats(channel_id: int, video_id: str, db: AsyncSession = Depends(get_db)):
    """Get detailed stats for a single video."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    youtube, creds = _get_youtube_service(channel)

    try:
        response = youtube.videos().list(
            part="statistics,snippet,contentDetails,status",
            id=video_id,
        ).execute()

        if not response.get("items"):
            raise HTTPException(status_code=404, detail="Video not found")

        v = response["items"][0]
        snippet = v.get("snippet", {})
        statistics = v.get("statistics", {})
        status = v.get("status", {})

        if creds.token != channel.access_token:
            channel.access_token = creds.token
            await db.commit()

        return {
            "success": True,
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "published_at": snippet.get("publishedAt", ""),
            "tags": snippet.get("tags", []),
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "view_count": int(statistics.get("viewCount", 0)),
            "like_count": int(statistics.get("likeCount", 0)),
            "comment_count": int(statistics.get("commentCount", 0)),
            "privacy": status.get("privacyStatus", ""),
            "license": status.get("license", ""),
            "embeddable": status.get("embeddable", False),
            "youtube_url": f"https://youtube.com/watch?v={video_id}",
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Video stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


# ── Analytics (views, watch time, CTR) ───────────────────────

@router.get("/analytics/{channel_id}")
async def get_analytics(
    channel_id: int,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """
    Pull analytics data for a channel.
    Uses YouTube Analytics API v2.
    Returns: views, watch_time, subs gained per day.
    """
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if not channel.youtube_channel_id:
        return {"success": False, "error": "YouTube Channel ID not set. Please add it in channel settings."}

    analytics, creds = _get_analytics_service(channel)

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        # Channel-level analytics
        channel_response = analytics.reports().query(
            ids=f"channel=={channel.youtube_channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewDuration,averageViewPercentage",
            dimensions="day",
            sort="day",
        ).execute()

        # Top videos analytics
        videos_response = analytics.reports().query(
            ids=f"channel=={channel.youtube_channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewPercentage,subscribersGained",
            dimensions="video",
            sort="-views",
            maxResults=20,
        ).execute()

        # Parse daily data
        daily = []
        col_headers = [h["name"] for h in channel_response.get("columnHeaders", [])]
        for row in channel_response.get("rows", []):
            entry = {}
            for i, h in enumerate(col_headers):
                entry[h] = row[i]
            daily.append(entry)

        # Parse top videos
        top_videos = []
        vid_headers = [h["name"] for h in videos_response.get("columnHeaders", [])]
        for row in videos_response.get("rows", []):
            entry = {}
            for i, h in enumerate(vid_headers):
                entry[h] = row[i]
            top_videos.append(entry)

        # Compute summary
        total_views = sum(d.get("views", 0) for d in daily)
        total_watch_min = sum(d.get("estimatedMinutesWatched", 0) for d in daily)
        total_subs_gained = sum(d.get("subscribersGained", 0) for d in daily)
        total_subs_lost = sum(d.get("subscribersLost", 0) for d in daily)

        if creds.token != channel.access_token:
            channel.access_token = creds.token
            await db.commit()

        return {
            "success": True,
            "channel": channel.name,
            "channel_id": channel_id,
            "period": f"{start_date} to {end_date} ({days} days)",
            "summary": {
                "total_views": total_views,
                "total_watch_hours": round(total_watch_min / 60, 1),
                "subs_gained": total_subs_gained,
                "subs_lost": total_subs_lost,
                "net_subs": total_subs_gained - total_subs_lost,
                "avg_view_duration_sec": round(sum(d.get("averageViewDuration", 0) for d in daily) / max(len(daily), 1), 1),
                "avg_view_percentage": round(sum(d.get("averageViewPercentage", 0) for d in daily) / max(len(daily), 1), 1),
            },
            "daily": daily,
            "top_videos": top_videos,
        }

    except Exception as e:
        log.error(f"YouTube Analytics error: {e}")
        if "quotaExceeded" in str(e):
            raise HTTPException(status_code=429, detail="YouTube API quota exceeded.")
        if "insufficientPermissions" in str(e) or "forbidden" in str(e).lower():
            raise HTTPException(status_code=403, detail="Insufficient permissions. Please re-authorize with Analytics scope.")
        if "invalid_grant" in str(e):
            raise HTTPException(status_code=401, detail="Token expired. Please re-authorize.")
        raise HTTPException(status_code=500, detail=f"Analytics error: {str(e)[:200]}")


# ── Channel Info ──────────────────────────────────────────────

@router.get("/channel-info/{channel_id}")
async def channel_info(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get YouTube channel info and sync to local DB."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    youtube, creds = _get_youtube_service(channel)

    try:
        response = youtube.channels().list(
            part="snippet,statistics,contentDetails,brandingSettings",
            mine=True,
        ).execute()

        if not response.get("items"):
            if channel.youtube_channel_id:
                response = youtube.channels().list(
                    part="snippet,statistics,contentDetails,brandingSettings",
                    id=channel.youtube_channel_id,
                ).execute()

        if not response.get("items"):
            return {"success": False, "error": "Channel not found"}

        ch = response["items"][0]
        snippet = ch.get("snippet", {})
        stats = ch.get("statistics", {})

        # Update local DB
        channel.youtube_channel_id = ch["id"]
        channel.subscriber_count = int(stats.get("subscriberCount", 0))
        channel.total_views = int(stats.get("viewCount", 0))
        channel.video_count = int(stats.get("videoCount", 0))

        if creds.token != channel.access_token:
            channel.access_token = creds.token

        await db.commit()

        return {
            "success": True,
            "youtube_channel_id": ch["id"],
            "title": snippet.get("title", ""),
            "description": snippet.get("description", "")[:200],
            "custom_url": snippet.get("customUrl", ""),
            "published_at": snippet.get("publishedAt", ""),
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "country": snippet.get("country", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "total_videos": int(stats.get("videoCount", 0)),
            "synced_to_db": True,
        }

    except Exception as e:
        log.error(f"Channel info error: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])
