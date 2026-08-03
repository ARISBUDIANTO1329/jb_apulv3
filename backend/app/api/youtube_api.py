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
from app.models.video_analytics import VideoAnalytics

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

    channel_has_ctr = False
    try:
        # Channel-level analytics — try CTR first, fallback to basic
        try:
            channel_response = analytics.reports().query(
                ids=f"channel=={channel.youtube_channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewDuration,averageViewPercentage,impressions,impressionClickThroughRate",
                dimensions="day",
                sort="day",
            ).execute()
            channel_has_ctr = True
        except Exception as ctr_err:
            if "impressions" in str(ctr_err).lower() or "Unknown identifier" in str(ctr_err):
                channel_has_ctr = False
                channel_response = analytics.reports().query(
                    ids=f"channel=={channel.youtube_channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewDuration,averageViewPercentage",
                    dimensions="day",
                    sort="day",
                ).execute()
            else:
                raise

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
        total_impressions = sum(d.get("impressions", 0) for d in daily) if channel_has_ctr else 0
        if channel_has_ctr:
            total_ctr_vals = [d.get("impressionClickThroughRate", 0) for d in daily if d.get("impressionClickThroughRate", 0) > 0]
            avg_ctr = round(sum(total_ctr_vals) / max(len(total_ctr_vals), 1), 1) if total_ctr_vals else 0
        else:
            avg_ctr = 0

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
                "total_impressions": total_impressions,
                "avg_ctr": avg_ctr,
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


# ── Video Performance Snapshot ──────────────────────────────

from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.video_analytics import VideoAnalytics


@router.post("/snapshot/{channel_id}")
async def take_snapshot(channel_id: int, max_results: int = 50, db: AsyncSession = Depends(get_db)):
    """
    Fetch per-video stats from YouTube Data API v3.
    Stores views, likes, engagement rate into video_analytics.
    One row per video per day.
    """
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    if not channel.youtube_channel_id:
        return {"success": False, "error": "YouTube Channel ID not set."}

    youtube, creds = _get_youtube_service(channel)
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    try:
        # Step 1: Get all video IDs from channel via search.list
        all_video_ids = []
        next_page = None
        while len(all_video_ids) < max_results:
            batch_size = min(50, max_results - len(all_video_ids))
            search_kwargs = dict(
                part="snippet",
                channelId=channel.youtube_channel_id,
                maxResults=batch_size,
                order="date",
                type="video",
            )
            if next_page:
                search_kwargs["pageToken"] = next_page
            search_resp = youtube.search().list(**search_kwargs).execute()
            items = search_resp.get("items", [])
            if not items:
                break
            all_video_ids.extend([item["id"]["videoId"] for item in items])
            next_page = search_resp.get("nextPageToken")
            if not next_page:
                break

        if not all_video_ids:
            return {"success": True, "message": "No videos found", "stored": 0}

        log.info(f"Found {len(all_video_ids)} videos for channel {channel.name}")

        # Step 2: Get stats for all videos (batch 50 at a time)
        all_stats = []
        for i in range(0, len(all_video_ids), 50):
            batch = all_video_ids[i:i+50]
            vids_resp = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(batch),
            ).execute()
            for item in vids_resp.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                all_stats.append({
                    "video_id": item["id"],
                    "title": snippet.get("title", ""),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                    "views": int(stats.get("viewCount", 0) or 0),
                    "likes": int(stats.get("likeCount", 0) or 0),
                    "comments": int(stats.get("commentCount", 0) or 0),
                    "published_at": snippet.get("publishedAt", ""),
                })

        # Step 3: Get yesterday's snapshots for growth calculation
        yesterday_rows = await db.execute(text(
            "SELECT video_id, views FROM video_analytics WHERE channel_id = :cid AND snapshot_date = :d"
        ), {"cid": channel_id, "d": yesterday})
        yesterday_map = {r.video_id: r.views for r in yesterday_rows}

        # Step 4: Upsert each video
        stored = 0
        for v in all_stats:
            vid = v["video_id"]
            views = v["views"]
            likes = v["likes"]
            # Engagement rate: (likes / views) * 100 — proxy for CTR
            engagement_rate = round((likes / views * 100), 2) if views > 0 else 0.0
            # Views growth: how many views gained since yesterday
            prev_views = yesterday_map.get(vid, 0)
            views_growth = max(0, views - prev_views)

            stmt = pg_insert(VideoAnalytics).values(
                channel_id=channel_id,
                video_id=vid,
                video_title=v["title"],
                thumbnail_url=v["thumbnail"],
                snapshot_date=today,
                impressions=views_growth,  # repurpose: daily views growth
                ctr=engagement_rate,       # repurpose: engagement rate %
                views=views,
                watch_minutes=0,
                avg_view_percentage=0,
                likes=likes,
                subs_gained=v["comments"],  # repurpose: comments count
            ).on_conflict_do_update(
                constraint="uq_video_snapshot",
                set_={
                    "impressions": views_growth,
                    "ctr": engagement_rate,
                    "views": views,
                    "likes": likes,
                    "subs_gained": v["comments"],
                    "video_title": v["title"],
                    "thumbnail_url": v["thumbnail"],
                },
            )
            await db.execute(stmt)
            stored += 1

        await db.commit()

        # Update token if refreshed
        if creds.token != channel.access_token:
            channel.access_token = creds.token
            await db.commit()

        return {
            "success": True,
            "stored": stored,
            "date": str(today),
            "channel": channel.name,
            "method": "data_api_v3",
        }

    except Exception as e:
        log.error(f"Snapshot error: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/performance/{channel_id}")
async def get_performance(
    channel_id: int,
    sort: str = "ctr",
    order: str = "desc",
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """
    Return video performance ranking from latest snapshot.
    Sort by: ctr, views, impressions, watch_minutes
    """
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Get latest snapshot date
    latest = await db.execute(text(
        "SELECT MAX(snapshot_date) FROM video_analytics WHERE channel_id = :cid"
    ), {"cid": channel_id})
    latest_date = latest.scalar()
    if not latest_date:
        return {"success": False, "error": "No snapshot data. Take a snapshot first.", "videos": []}

    # Sort column mapping
    sort_map = {
        "ctr": "ctr",
        "views": "views",
        "impressions": "impressions",
        "watch_minutes": "watch_minutes",
    }
    sort_col = sort_map.get(sort, "ctr")
    order_dir = "DESC" if order == "desc" else "ASC"

    rows = await db.execute(text(f"""
        SELECT video_id, video_title, thumbnail_url,
               impressions, ctr, views, watch_minutes, likes,
               avg_view_percentage, subs_gained
        FROM video_analytics
        WHERE channel_id = :cid AND snapshot_date = :d
        ORDER BY {sort_col} {order_dir}
        LIMIT :lim
    """), {"cid": channel_id, "d": latest_date, "lim": limit})

    videos = []
    for r in rows:
        engagement = r.ctr
        alert = "low" if engagement < 1.0 else "medium" if engagement < 2.0 else "high"
        recommendation = ""
        if alert == "low":
            recommendation = "⚠️ Low engagement. Consider changing thumbnail or title."
        elif alert == "medium":
            recommendation = "📊 Medium engagement. Test new thumbnail design."
        
        videos.append({
            "video_id": r.video_id,
            "title": r.video_title,
            "thumbnail_url": r.thumbnail_url,
            "impressions": r.impressions,
            "engagement": round(engagement, 2),
            "views": r.views,
            "watch_minutes": round(r.watch_minutes, 1),
            "avg_view_percentage": r.avg_view_percentage,
            "likes": r.likes,
            "engagement_alert": alert,
            "recommendation": recommendation,
            "youtube_url": f"https://youtube.com/watch?v={r.video_id}",
        })

    return {
        "success": True,
        "channel": channel.name,
        "channel_id": channel_id,
        "snapshot_date": str(latest_date),
        "sort": sort,
        "order": order,
        "total": len(videos),
        "videos": videos,
    }


@router.get("/video-trend/{channel_id}/{video_id}")
async def get_video_trend(channel_id: int, video_id: str, days: int = 7, db: AsyncSession = Depends(get_db)):
    """Get 7-day views trend for a video — track growth/stagnation."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Get last N days snapshots for this video
    rows = await db.execute(text("""
        SELECT snapshot_date, views, likes, ctr 
        FROM video_analytics 
        WHERE channel_id = :cid AND video_id = :vid
        ORDER BY snapshot_date DESC
        LIMIT :days
    """), {"cid": channel_id, "vid": video_id, "days": days})

    snapshots = [dict(r._mapping) for r in rows]
    snapshots.reverse()  # oldest first

    if not snapshots:
        return {"success": False, "error": "No trend data", "video_id": video_id}

    # Calculate trend
    first_views = snapshots[0]["views"]
    last_views = snapshots[-1]["views"]
    growth = last_views - first_views
    growth_pct = round((growth / max(first_views, 1)) * 100, 1)

    # Trend direction
    if growth_pct > 5:
        trend = "up"
    elif growth_pct < -5:
        trend = "down"
    else:
        trend = "flat"

    return {
        "success": True,
        "video_id": video_id,
        "channel": channel.name,
        "snapshots": [{"date": str(s["snapshot_date"]), "views": s["views"], "likes": s["likes"]} for s in snapshots],
        "first_views": first_views,
        "last_views": last_views,
        "growth": growth,
        "growth_pct": growth_pct,
        "trend": trend,
        "recommendation": "📈 Growing — keep this style" if trend == "up" else "📉 Declining — change thumbnail" if trend == "down" else "➡️ Stable — hold strategy",
    }


@router.get("/best-upload-time/{channel_id}")
async def get_best_upload_time(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Analyze best day/hour to upload based on high-engagement videos."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    youtube, _ = _get_youtube_service(channel)

    try:
        # Get videos with highest engagement
        rows = await db.execute(text("""
            SELECT video_id FROM video_analytics
            WHERE channel_id = :cid
            ORDER BY ctr DESC
            LIMIT 10
        """), {"cid": channel_id})
        
        video_ids = [r[0] for r in rows]
        if not video_ids:
            return {"success": False, "error": "No video data", "videos": []}

        # Get video details including publishedAt
        vids_resp = youtube.videos().list(
            part="snippet",
            id=",".join(video_ids[:10]),
        ).execute()

        # Analyze publish times
        publish_times = []
        for item in vids_resp.get("items", []):
            pub_at = item["snippet"].get("publishedAt", "")
            if pub_at:
                from datetime import datetime
                dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][dt.weekday()]
                hour = dt.hour
                publish_times.append({
                    "day": day_name,
                    "hour": hour,
                    "date": pub_at[:10],
                })

        if not publish_times:
            return {"success": False, "error": "No publish times found"}

        # Count by day
        day_counts = {}
        for pt in publish_times:
            day = pt["day"]
            day_counts[day] = day_counts.get(day, 0) + 1

        best_day = max(day_counts.items(), key=lambda x: x[1])[0]

        # Count by hour
        hour_counts = {}
        for pt in publish_times:
            hour = pt["hour"]
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        best_hour = max(hour_counts.items(), key=lambda x: x[1])[0]

        return {
            "success": True,
            "channel": channel.name,
            "analysis_videos": len(publish_times),
            "best_day": best_day,
            "best_hour": best_hour,
            "day_distribution": day_counts,
            "hour_distribution": hour_counts,
            "recommendation": f"📅 Upload on {best_day} at {best_hour:02d}:00 for best engagement",
            "publish_times": publish_times,
        }

    except Exception as e:
        log.error(f"Best upload time error: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])
