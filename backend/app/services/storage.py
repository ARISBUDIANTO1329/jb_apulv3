import os
import shutil
from pathlib import Path
from app.core.config import settings


class StorageService:
    """Per-channel file storage management."""

    ASSET_TYPES = [
        "video-raw", "video", "video-live", "video-preview",
        "upload_ready", "livestream-ready",
        "mp3", "sfx", "intro", "thumbnail", "shorts", "metadata",
    ]

    def __init__(self):
        self.base_path = Path(settings.STORAGE_PATH)

    def get_channel_path(self, channel_id: int, asset_type: str) -> Path:
        """Get the storage path for a specific channel and asset type."""
        if asset_type not in self.ASSET_TYPES:
            raise ValueError(f"Invalid asset type: {asset_type}")
        path = self.base_path / "assets" / asset_type / str(channel_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_upload_ready_path(self, channel_id: int) -> Path:
        """Get the upload_ready directory for a channel."""
        return self.get_channel_path(channel_id, "upload_ready")

    def get_raw_video_path(self, channel_id: int) -> Path:
        """Get the raw video directory for a channel."""
        return self.get_channel_path(channel_id, "video-raw")

    def get_mp3_path(self, channel_id: int) -> Path:
        """Get the MP3 directory for a channel."""
        return self.get_channel_path(channel_id, "mp3")

    def get_sfx_path(self, channel_id: int) -> Path:
        """Get the SFX directory for a channel."""
        return self.get_channel_path(channel_id, "sfx")

    def get_livestream_ready_path(self, channel_id: int) -> Path:
        """Get the livestream-ready directory for a channel."""
        return self.get_channel_path(channel_id, "livestream-ready")

    def list_files(self, channel_id: int, asset_type: str) -> list[dict]:
        """List all files in a channel's asset directory."""
        path = self.get_channel_path(channel_id, asset_type)
        files = []
        for f in path.iterdir():
            if f.is_file():
                files.append({
                    "filename": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                })
        return sorted(files, key=lambda x: x["filename"])

    def save_file(self, channel_id: int, asset_type: str, filename: str, content: bytes) -> str:
        """Save a file to a channel's asset directory."""
        path = self.get_channel_path(channel_id, asset_type) / filename
        path.write_bytes(content)
        return str(path)

    def delete_file(self, file_path: str) -> bool:
        """Delete a file. Handles both absolute and relative paths."""
        try:
            path = Path(file_path)
            # If path is relative, prepend base_path
            if not path.is_absolute():
                path = self.base_path / path
            path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def move_to_uploaded(self, file_path: str, channel_id: int) -> str:
        """Move a file to the uploaded archive."""
        source = Path(file_path)
        archive = self.get_channel_path(channel_id, "upload_ready") / "uploaded"
        archive.mkdir(parents=True, exist_ok=True)
        dest = archive / source.name
        shutil.move(str(source), str(dest))
        return str(dest)

    def get_tmp_path(self, filename: str) -> Path:
        """Get a temporary file path."""
        tmp = self.base_path / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp / filename

    def cleanup_tmp(self, max_age_hours: int = 24) -> int:
        """Clean up old temporary files."""
        import time
        tmp = self.base_path / "tmp"
        if not tmp.exists():
            return 0
        cutoff = time.time() - (max_age_hours * 3600)
        count = 0
        for f in tmp.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                count += 1
        return count

    def get_channel_stats(self, channel_id: int) -> dict:
        """Get storage stats for a channel."""
        stats = {}
        for asset_type in self.ASSET_TYPES:
            path = self.base_path / "assets" / asset_type / str(channel_id)
            if path.exists():
                files = list(path.iterdir())
                total_size = sum(f.stat().st_size for f in files if f.is_file())
                stats[asset_type] = {
                    "count": len(files),
                    "size_mb": round(total_size / 1024 / 1024, 2),
                }
            else:
                stats[asset_type] = {"count": 0, "size_mb": 0}
        return stats


# Singleton
storage = StorageService()
