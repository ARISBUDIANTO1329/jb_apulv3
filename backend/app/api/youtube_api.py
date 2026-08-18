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
from sqlalchemy import select, text, func

from app.db.session import get_db
from app.models.channel import Channel
from app.models.video_analytics import VideoAnalytics
from app.services.google_token_service import get_youtube_client, get_analytics_client

router = APIRouter()
log = logging.getLogger("youtube_api")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")




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

    youtube, creds = await get_youtube_client(channel, db)

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

    youtube, creds = await get_youtube_client(channel, db)

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

    analytics, creds = await get_analytics_client(channel, db)

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

    youtube, creds = await get_youtube_client(channel, db)

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
from app.services.google_token_service import get_youtube_client, get_analytics_client


@router.post("/snapshot/{channel_id}")
async def snapshot_videos(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch per-video metrics from YouTube Analytics. Fallback if impressions unavailable."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    analytics, creds = await get_analytics_client(channel, db)
    youtube, _ = await get_youtube_client(channel, db)

    try:
        today = datetime.now(timezone.utc).date()
        start_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        videos_response = None
        try:
            videos_response = analytics.reports().query(
                ids=f"channel=={channel.youtube_channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewPercentage,subscribersGained,impressions,impressionClickThroughRate",
                dimensions="video",
                sort="-impressionClickThroughRate",
                maxResults=200,
            ).execute()
        except Exception as e:
            if "impressions" in str(e).lower() or "Unknown identifier" in str(e):
                log.info("Impressions unavailable, using views fallback")
                videos_response = analytics.reports().query(
                    ids=f"channel=={channel.youtube_channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewPercentage,subscribersGained",
                    dimensions="video",
                    sort="-views",
                    maxResults=200,
                ).execute()
            else:
                raise

        vid_headers = [h["name"] for h in videos_response.get("columnHeaders", [])]
        video_rows = []
        for row in videos_response.get("rows", []):
            entry = {vid_headers[i]: row[i] if i < len(row) else None for i in range(len(vid_headers))}
            video_rows.append(entry)

        if not video_rows:
            return {"success": True, "total_videos": 0, "avg_ctr": 0}

        video_ids = [v.get("video") for v in video_rows if v.get("video")]
        video_details = {}
        if video_ids:
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i:i+50]
                vids_resp = youtube.videos().list(part="snippet", id=",".join(batch)).execute()
                for item in vids_resp.get("items", []):
                    vid_id = item["id"]
                    video_details[vid_id] = {
                        "title": item["snippet"].get("title", ""),
                        "thumbnail": item["snippet"].get("thumbnails", {}).get("medium", {}).get("url", ""),
                    }

        from sqlalchemy.dialects.postgresql import insert
        records = []
        for v in video_rows:
            vid_id = v.get("video", "")
            if not vid_id:
                continue
            ctr_val = float(v.get("impressionClickThroughRate", 0)) if v.get("impressionClickThroughRate") else 0.0
            records.append({
                "channel_id": channel_id,
                "video_id": vid_id,
                "video_title": video_details.get(vid_id, {}).get("title", ""),
                "thumbnail_url": video_details.get(vid_id, {}).get("thumbnail", ""),
                "snapshot_date": today,
                "impressions": int(v.get("impressions", 0)) if v.get("impressions") else 0,
                "ctr": ctr_val,
                "views": int(v.get("views", 0)) if v.get("views") else 0,
                "watch_minutes": float(v.get("estimatedMinutesWatched", 0)) if v.get("estimatedMinutesWatched") else 0.0,
                "avg_view_percentage": float(v.get("averageViewPercentage", 0)) if v.get("averageViewPercentage") else 0.0,
                "likes": 0,
                "subs_gained": int(v.get("subscribersGained", 0)) if v.get("subscribersGained") else 0,
            })

        if records:
            stmt = insert(VideoAnalytics).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["video_id", "snapshot_date"],
                set_={col.name: getattr(stmt.excluded, col.name) for col in VideoAnalytics.__table__.columns if col.name not in ["id", "created_at"]}
            )
            await db.execute(stmt)
            await db.commit()

        ctr_vals = [float(v.get("impressionClickThroughRate", 0)) for v in video_rows if v.get("impressionClickThroughRate")]
        avg_ctr = round(sum(ctr_vals) / len(ctr_vals), 2) if ctr_vals else 0

        if creds.token != channel.access_token:
            channel.access_token = creds.token
            await db.commit()

        return {"success": True, "total_videos": len(video_rows), "avg_ctr": avg_ctr, "snapshot_date": str(today)}

    except Exception as e:
        log.error(f"Snapshot error: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])

# ── Performance: Ranked Videos by CTR ──────────────────────────

@router.get("/performance/{channel_id}")
async def get_video_performance(channel_id: int, sort: str = "ctr", order: str = "desc", limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Query video_analytics for latest snapshot. Return ranked videos."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    try:
        latest_snapshot = await db.execute(
            select(func.max(VideoAnalytics.snapshot_date))
            .where(VideoAnalytics.channel_id == channel_id)
        )
        snapshot_date = latest_snapshot.scalar()

        if not snapshot_date:
            return {"success": False, "error": "No snapshot data yet", "videos": []}

        query = select(VideoAnalytics).where(
            VideoAnalytics.channel_id == channel_id,
            VideoAnalytics.snapshot_date == snapshot_date,
        )

        sort_col = {
            "ctr": VideoAnalytics.ctr,
            "views": VideoAnalytics.views,
            "impressions": VideoAnalytics.impressions,
            "watch_minutes": VideoAnalytics.watch_minutes,
        }.get(sort, VideoAnalytics.ctr)

        if order == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        query = query.limit(limit)
        result = await db.execute(query)
        videos = result.scalars().all()

        video_list = [
            {
                "video_id": v.video_id,
                "title": v.video_title or "Unknown",
                "thumbnail_url": v.thumbnail_url or "",
                "impressions": v.impressions,
                "ctr": v.ctr,
                "views": v.views,
                "watch_minutes": v.watch_minutes,
                "avg_view_percentage": v.avg_view_percentage,
                "likes": v.likes,
                "subs_gained": v.subs_gained,
            }
            for v in videos
        ]

        return {
            "success": True,
            "channel": channel.name,
            "channel_id": channel_id,
            "snapshot_date": str(snapshot_date),
            "sort": sort,
            "order": order,
            "total_videos": len(video_list),
            "videos": video_list,
        }

    except Exception as e:
        log.error(f"Performance query error: {e}")
        raise HTTPException(status_code=500, detail="Query failed")
