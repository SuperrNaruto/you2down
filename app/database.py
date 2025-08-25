"""数据库模块."""

import aiosqlite
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class VideoInfo:
    """视频信息数据类."""
    id: str
    title: str
    url: str
    playlist_id: str
    status: str = "pending"
    file_path: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class PlaylistInfo:
    """播放列表信息数据类."""
    id: str
    title: Optional[str] = None
    last_checked: Optional[datetime] = None
    last_video_count: int = 0


class Database:
    """数据库操作类."""
    
    def __init__(self, db_path: str = "/app/data/app.db"):
        """初始化数据库."""
        self.db_path = db_path
        self._lock = asyncio.Lock()
    
    async def init(self) -> None:
        """初始化数据库表."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    playlist_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    file_path TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS playlists (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    last_checked TIMESTAMP,
                    last_video_count INTEGER DEFAULT 0
                )
            """)
            
            await db.commit()
    
    async def add_video(self, video: VideoInfo) -> bool:
        """添加视频记录."""
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO videos 
                        (id, title, url, playlist_id, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        video.id, video.title, video.url, video.playlist_id,
                        video.status, datetime.now(), datetime.now()
                    ))
                    await db.commit()
                return True
            except Exception as e:
                print(f"添加视频记录失败: {e}")
                return False
    
    async def update_video_status(
        self, 
        video_id: str, 
        status: str,
        file_path: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """更新视频状态."""
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("""
                        UPDATE videos 
                        SET status = ?, file_path = ?, error_message = ?, updated_at = ?
                        WHERE id = ?
                    """, (status, file_path, error_message, datetime.now(), video_id))
                    await db.commit()
                return True
            except Exception as e:
                print(f"更新视频状态失败: {e}")
                return False
    
    async def increment_retry_count(self, video_id: str) -> bool:
        """增加重试次数."""
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("""
                        UPDATE videos 
                        SET retry_count = retry_count + 1, updated_at = ?
                        WHERE id = ?
                    """, (datetime.now(), video_id))
                    await db.commit()
                return True
            except Exception as e:
                print(f"增加重试次数失败: {e}")
                return False
    
    async def get_video(self, video_id: str) -> Optional[VideoInfo]:
        """获取视频信息."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, title, url, playlist_id, status, file_path, 
                       error_message, retry_count, created_at, updated_at
                FROM videos WHERE id = ?
            """, (video_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return VideoInfo(*row)
                return None
    
    async def get_pending_videos(self) -> List[VideoInfo]:
        """获取待处理的视频."""
        videos = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, title, url, playlist_id, status, file_path, 
                       error_message, retry_count, created_at, updated_at
                FROM videos WHERE status = 'pending'
                ORDER BY created_at ASC
            """) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    videos.append(VideoInfo(*row))
        return videos
    
    async def get_videos_by_status(self, status: str) -> List[VideoInfo]:
        """根据状态获取视频列表."""
        videos = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, title, url, playlist_id, status, file_path, 
                       error_message, retry_count, created_at, updated_at
                FROM videos WHERE status = ?
                ORDER BY updated_at DESC
            """, (status,)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    videos.append(VideoInfo(*row))
        return videos
    
    async def video_exists(self, video_id: str) -> bool:
        """检查视频是否存在."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT 1 FROM videos WHERE id = ? LIMIT 1
            """, (video_id,)) as cursor:
                row = await cursor.fetchone()
                return row is not None
    
    async def update_playlist_info(self, playlist: PlaylistInfo) -> bool:
        """更新播放列表信息."""
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO playlists 
                        (id, title, last_checked, last_video_count)
                        VALUES (?, ?, ?, ?)
                    """, (
                        playlist.id, playlist.title, 
                        playlist.last_checked, playlist.last_video_count
                    ))
                    await db.commit()
                return True
            except Exception as e:
                print(f"更新播放列表信息失败: {e}")
                return False
    
    async def get_playlist_info(self, playlist_id: str) -> Optional[PlaylistInfo]:
        """获取播放列表信息."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, title, last_checked, last_video_count
                FROM playlists WHERE id = ?
            """, (playlist_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    playlist_id, title, last_checked_str, last_video_count = row
                    # 转换last_checked从字符串到datetime对象
                    last_checked = None
                    if last_checked_str:
                        try:
                            last_checked = datetime.fromisoformat(last_checked_str.replace('Z', '+00:00'))
                        except Exception as e:
                            print(f"解析日期时间失败: {last_checked_str}, 错误: {e}")
                    
                    return PlaylistInfo(
                        id=playlist_id,
                        title=title,
                        last_checked=last_checked,
                        last_video_count=last_video_count
                    )
                return None
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息."""
        stats = {}
        async with aiosqlite.connect(self.db_path) as db:
            # 总视频数
            async with db.execute("SELECT COUNT(*) FROM videos") as cursor:
                stats["total_videos"] = (await cursor.fetchone())[0]
            
            # 各状态视频数
            async with db.execute("""
                SELECT status, COUNT(*) FROM videos GROUP BY status
            """) as cursor:
                status_counts = await cursor.fetchall()
                stats["status_counts"] = dict(status_counts)
            
            # 播放列表数
            async with db.execute("SELECT COUNT(*) FROM playlists") as cursor:
                stats["total_playlists"] = (await cursor.fetchone())[0]
        
        return stats