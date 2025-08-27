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
    # Google Drive相关字段
    description: Optional[str] = None  # 视频描述，用于检测Drive链接
    gdrive_links: Optional[str] = None  # JSON字符串存储检测到的Drive链接
    gdrive_status: str = "none"  # none, detected, downloading, completed, failed
    gdrive_file_count: int = 0  # 关联的Drive文件数量

@dataclass
class DriveFileInfo:
    """Google Drive文件信息数据类."""
    id: str  # 主键ID（自动生成）
    video_id: str  # 关联的视频ID
    file_id: str  # Google Drive文件ID
    filename: str
    original_url: str
    link_type: str  # file, document, spreadsheet, etc.
    status: str = "pending"  # pending, downloading, completed, failed, uploaded
    file_path: Optional[str] = None
    file_size: Optional[int] = None
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
    download_strategy: str = "both"  # both, video_only, gdrive_only


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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT,
                    gdrive_links TEXT,
                    gdrive_status TEXT DEFAULT 'none',
                    gdrive_file_count INTEGER DEFAULT 0
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS playlists (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    last_checked TIMESTAMP,
                    last_video_count INTEGER DEFAULT 0,
                    download_strategy TEXT DEFAULT 'both'
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS drive_files (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    original_url TEXT NOT NULL,
                    link_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    file_path TEXT,
                    file_size INTEGER,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos (id)
                )
            """)
            
            # Instagram媒体表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS instagram_media (
                    id TEXT PRIMARY KEY,
                    shortcode TEXT NOT NULL UNIQUE,
                    url TEXT NOT NULL,
                    username TEXT NOT NULL,
                    caption TEXT,
                    timestamp TIMESTAMP NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    file_path TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Instagram检查记录表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS instagram_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    last_checked TIMESTAMP NOT NULL,
                    media_count INTEGER DEFAULT 0,
                    new_media_count INTEGER DEFAULT 0
                )
            """)
            
            # 为现有播放列表添加下载策略字段（如果不存在）
            if not await self._column_exists(db, 'playlists', 'download_strategy'):
                await db.execute("""
                    ALTER TABLE playlists ADD COLUMN download_strategy TEXT DEFAULT 'both'
                """)
            
            # 为现有视频表添加描述字段（如果不存在）
            if not await self._column_exists(db, 'videos', 'description'):
                await db.execute("""
                    ALTER TABLE videos ADD COLUMN description TEXT
                """)
            
            await db.commit()
    
    async def _column_exists(self, db, table_name: str, column_name: str) -> bool:
        """检查表中是否存在指定列."""
        try:
            async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
                columns = await cursor.fetchall()
                return any(col[1] == column_name for col in columns)
        except Exception:
            return False
    
    async def add_video(self, video: VideoInfo) -> bool:
        """添加视频记录."""
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO videos 
                        (id, title, url, playlist_id, status, description, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        video.id, video.title, video.url, video.playlist_id,
                        video.status, video.description, datetime.now(), datetime.now()
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
                       error_message, retry_count, created_at, updated_at, description
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
                       error_message, retry_count, created_at, updated_at, description
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
                       error_message, retry_count, created_at, updated_at, description
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

    
    async def set_playlist_strategy(self, playlist_id: str, strategy: str) -> None:
        """设置播放列表的下载策略."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT OR IGNORE INTO playlists (id, download_strategy)
                    VALUES (?, ?)
                """, (playlist_id, strategy))
                
                await db.execute("""
                    UPDATE playlists 
                    SET download_strategy = ?, updated_at = ?
                    WHERE id = ?
                """, (strategy, datetime.now(), playlist_id))
                
                await db.commit()
    
    async def get_playlist_strategy(self, playlist_id: str) -> str:
        """获取播放列表的下载策略."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT download_strategy FROM playlists WHERE id = ?
            """, (playlist_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 'both'
    
    async def get_all_playlist_strategies(self) -> Dict[str, str]:
        """获取所有播放列表的下载策略."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, download_strategy FROM playlists
            """) as cursor:
                rows = await cursor.fetchall()
                return {row[0]: row[1] for row in rows}
    
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

    async def add_drive_file(self, drive_file: DriveFileInfo) -> None:
        """添加Google Drive文件记录."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO drive_files 
                (id, video_id, file_id, filename, original_url, link_type, status,
                 file_path, file_size, error_message, retry_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                drive_file.id, drive_file.video_id, drive_file.file_id,
                drive_file.filename, drive_file.original_url, drive_file.link_type,
                drive_file.status, drive_file.file_path, drive_file.file_size,
                drive_file.error_message, drive_file.retry_count,
                drive_file.created_at or datetime.now(),
                drive_file.updated_at or datetime.now()
            ))
            await db.commit()
    
    async def update_drive_file_status(
        self,
        file_id: str,
        status: str,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> None:
        """更新Google Drive文件状态."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE drive_files 
                    SET status = ?, file_path = ?, file_size = ?, 
                        error_message = ?, updated_at = ?
                    WHERE file_id = ?
                """, (status, file_path, file_size, error_message, datetime.now(), file_id))
                await db.commit()
    
    async def get_pending_drive_files(self) -> List[DriveFileInfo]:
        """获取待下载的Google Drive文件."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT * FROM drive_files 
                WHERE status = 'pending'
                ORDER BY created_at ASC
            """) as cursor:
                rows = await cursor.fetchall()
                
                drive_files = []
                for row in rows:
                    drive_file = DriveFileInfo(
                        id=row[0], video_id=row[1], file_id=row[2], filename=row[3],
                        original_url=row[4], link_type=row[5], status=row[6],
                        file_path=row[7], file_size=row[8], error_message=row[9],
                        retry_count=row[10], created_at=row[11], updated_at=row[12]
                    )
                    drive_files.append(drive_file)
                
                return drive_files
    
    async def get_drive_files_by_video(self, video_id: str) -> List[DriveFileInfo]:
        """获取指定视频关联的Google Drive文件."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT * FROM drive_files 
                WHERE video_id = ?
                ORDER BY created_at ASC
            """, (video_id,)) as cursor:
                rows = await cursor.fetchall()
                
                drive_files = []
                for row in rows:
                    drive_file = DriveFileInfo(
                        id=row[0], video_id=row[1], file_id=row[2], filename=row[3],
                        original_url=row[4], link_type=row[5], status=row[6],
                        file_path=row[7], file_size=row[8], error_message=row[9],
                        retry_count=row[10], created_at=row[11], updated_at=row[12]
                    )
                    drive_files.append(drive_file)
                
                return drive_files
    
    async def update_video_gdrive_status(
        self,
        video_id: str,
        gdrive_links: Optional[str] = None,
        gdrive_status: Optional[str] = None,
        gdrive_file_count: Optional[int] = None
    ) -> None:
        """更新视频的Google Drive状态."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                updates = []
                params = []
                
                if gdrive_links is not None:
                    updates.append("gdrive_links = ?")
                    params.append(gdrive_links)
                
                if gdrive_status is not None:
                    updates.append("gdrive_status = ?")
                    params.append(gdrive_status)
                
                if gdrive_file_count is not None:
                    updates.append("gdrive_file_count = ?")
                    params.append(gdrive_file_count)
                
                if updates:
                    updates.append("updated_at = ?")
                    params.append(datetime.now())
                    params.append(video_id)
                    
                    sql = f"UPDATE videos SET {', '.join(updates)} WHERE id = ?"
                    await db.execute(sql, params)
                    await db.commit()
    
    async def increment_drive_file_retry(self, file_id: str) -> None:
        """增加Google Drive文件重试次数."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE drive_files 
                    SET retry_count = retry_count + 1, updated_at = ?
                    WHERE file_id = ?
                """, (datetime.now(), file_id))
                await db.commit()
    
    async def get_drive_file_by_id(self, file_id: str) -> Optional[DriveFileInfo]:
        """根据文件ID获取Google Drive文件信息."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT * FROM drive_files WHERE file_id = ?
            """, (file_id,)) as cursor:
                row = await cursor.fetchone()
                
                if row:
                    return DriveFileInfo(
                        id=row[0], video_id=row[1], file_id=row[2], filename=row[3],
                        original_url=row[4], link_type=row[5], status=row[6],
                        file_path=row[7], file_size=row[8], error_message=row[9],
                        retry_count=row[10], created_at=row[11], updated_at=row[12]
                    )
                return None
    
    async def get_drive_files_by_status(self, status: str) -> List[DriveFileInfo]:
        """根据状态获取Google Drive文件列表."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT * FROM drive_files 
                WHERE status = ?
                ORDER BY created_at ASC
            """, (status,)) as cursor:
                rows = await cursor.fetchall()
                
                drive_files = []
                for row in rows:
                    drive_file = DriveFileInfo(
                        id=row[0], video_id=row[1], file_id=row[2], filename=row[3],
                        original_url=row[4], link_type=row[5], status=row[6],
                        file_path=row[7], file_size=row[8], error_message=row[9],
                        retry_count=row[10], created_at=row[11], updated_at=row[12]
                    )
                    drive_files.append(drive_file)
                
                return drive_files
    
    async def get_drive_files_stats(self) -> Dict[str, Any]:
        """获取Google Drive文件统计信息."""
        async with aiosqlite.connect(self.db_path) as db:
            # 总文件数
            async with db.execute("SELECT COUNT(*) FROM drive_files") as cursor:
                total_files = (await cursor.fetchone())[0]
            
            # 按状态统计
            async with db.execute("""
                SELECT status, COUNT(*) FROM drive_files GROUP BY status
            """) as cursor:
                status_counts = {row[0]: row[1] for row in await cursor.fetchall()}
            
            # 总文件大小
            async with db.execute("""
                SELECT SUM(file_size) FROM drive_files WHERE file_size IS NOT NULL
            """) as cursor:
                total_size = (await cursor.fetchone())[0] or 0
            
            # 今日处理统计
            async with db.execute("""
                SELECT status, COUNT(*) FROM drive_files 
                WHERE date(created_at) = date('now')
                GROUP BY status
            """) as cursor:
                today_stats = {row[0]: row[1] for row in await cursor.fetchall()}
            
            return {
                "total_files": total_files,
                "status_breakdown": status_counts,
                "total_size_bytes": total_size,
                "today_stats": today_stats
            }
    
    # Instagram相关方法
    
    async def add_instagram_media(self, media_id: str, shortcode: str, url: str, 
                                username: str, caption: str, timestamp: datetime) -> None:
        """添加Instagram媒体记录."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                try:
                    await db.execute("""
                        INSERT INTO instagram_media 
                        (id, shortcode, url, username, caption, timestamp, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (media_id, shortcode, url, username, caption, timestamp, 
                         datetime.now(), datetime.now()))
                    await db.commit()
                except Exception as e:
                    if "UNIQUE constraint failed" in str(e):
                        # 媒体已存在，更新信息
                        await db.execute("""
                            UPDATE instagram_media 
                            SET url = ?, username = ?, caption = ?, timestamp = ?, updated_at = ?
                            WHERE shortcode = ?
                        """, (url, username, caption, timestamp, datetime.now(), shortcode))
                        await db.commit()
                    else:
                        raise
    
    async def get_instagram_media_by_status(self, status: str = 'pending') -> List[Dict]:
        """根据状态获取Instagram媒体列表."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, shortcode, url, username, caption, timestamp, status, file_path, 
                       error_message, retry_count, created_at, updated_at
                FROM instagram_media 
                WHERE status = ? 
                ORDER BY timestamp DESC
            """, (status,)) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        'id': row[0], 'shortcode': row[1], 'url': row[2], 
                        'username': row[3], 'caption': row[4], 'timestamp': row[5],
                        'status': row[6], 'file_path': row[7], 'error_message': row[8],
                        'retry_count': row[9], 'created_at': row[10], 'updated_at': row[11]
                    }
                    for row in rows
                ]
    
    async def update_instagram_media_status(self, shortcode: str, status: str, 
                                          file_path: Optional[str] = None,
                                          error_message: Optional[str] = None) -> None:
        """更新Instagram媒体状态."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE instagram_media 
                    SET status = ?, file_path = ?, error_message = ?, updated_at = ?
                    WHERE shortcode = ?
                """, (status, file_path, error_message, datetime.now(), shortcode))
                await db.commit()
    
    async def increment_instagram_retry(self, shortcode: str) -> None:
        """增加Instagram媒体重试次数."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    UPDATE instagram_media 
                    SET retry_count = retry_count + 1, updated_at = ?
                    WHERE shortcode = ?
                """, (datetime.now(), shortcode))
                await db.commit()
    
    async def record_instagram_check(self, username: str, media_count: int, new_media_count: int) -> None:
        """记录Instagram检查结果."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO instagram_checks (username, last_checked, media_count, new_media_count)
                    VALUES (?, ?, ?, ?)
                """, (username, datetime.now(), media_count, new_media_count))
                await db.commit()
    
    async def get_instagram_stats(self) -> Dict[str, Any]:
        """获取Instagram统计信息."""
        async with aiosqlite.connect(self.db_path) as db:
            # 总媒体数
            async with db.execute("SELECT COUNT(*) FROM instagram_media") as cursor:
                total_count = (await cursor.fetchone())[0]
            
            # 按状态统计
            async with db.execute("""
                SELECT status, COUNT(*) FROM instagram_media GROUP BY status
            """) as cursor:
                status_stats = {row[0]: row[1] for row in await cursor.fetchall()}
            
            # 最近检查记录
            async with db.execute("""
                SELECT username, last_checked, media_count, new_media_count 
                FROM instagram_checks 
                ORDER BY last_checked DESC 
                LIMIT 1
            """) as cursor:
                last_check = await cursor.fetchone()
            
            return {
                'total_media': total_count,
                'status_breakdown': status_stats,
                'last_check': {
                    'username': last_check[0] if last_check else None,
                    'time': last_check[1] if last_check else None,
                    'media_count': last_check[2] if last_check else 0,
                    'new_media_count': last_check[3] if last_check else 0
                } if last_check else None
            }
