"""视频下载管理器模块."""

import os
import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass
import yt_dlp

from config import Settings
from database import VideoInfo, Database
from telegram_bot import TelegramNotifier


@dataclass
class DownloadResult:
    """下载结果."""
    success: bool
    file_path: Optional[str] = None
    error: Optional[str] = None
    video_info: Optional[Dict[str, Any]] = None


class VideoDownloader:
    """视频下载管理器."""
    
    def __init__(
        self, 
        config: Settings, 
        database: Database,
        telegram: TelegramNotifier
    ):
        """初始化下载管理器."""
        self.config = config
        self.db = database
        self.telegram = telegram
        self._semaphore = asyncio.Semaphore(config.max_concurrent_downloads)
        self._download_complete_callback: Optional[Callable[[], Awaitable[None]]] = None
        
        # yt-dlp配置
        self.ytdlp_options = {
            # 根据配置设置视频质量
            'format': self._get_quality_format(config.video_quality),
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(
                config.download_path, 
                '%(uploader)s - %(title).100s [%(id)s].%(ext)s'
            ),
            'writeinfojson': True,
            'writethumbnail': False,
            'concurrent_fragments': 4,
            'retries': 5,
            'fragment_retries': 3,
            'sleep_interval': 1,
            'max_sleep_interval': 5,
            'extractaudio': False,
            'audioformat': 'mp3',
            'embed_chapters': True,
            'embed_metadata': True,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': False,
            'no_warnings': False,
        }
    
    def _get_quality_format(self, quality: str) -> str:
        """根据质量设置获取格式字符串."""
        quality_formats = {
            'best': 'bestvideo+bestaudio/best',  # 最高质量，包括4K/8K
            '4k': 'bestvideo[height<=2160]+bestaudio/best[height<=2160]',  # 4K
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',  # 1080p
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',   # 720p
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',   # 480p
        }
        return quality_formats.get(quality.lower(), quality_formats['best'])
    
    def set_download_complete_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """设置下载完成回调."""
        self._download_complete_callback = callback
    
    async def _run_ytdlp(self, video_url: str) -> DownloadResult:
        """运行yt-dlp下载视频."""
        def _download():
            """同步下载函数."""
            try:
                with yt_dlp.YoutubeDL(self.ytdlp_options) as ydl:
                    # 先提取信息
                    info = ydl.extract_info(video_url, download=False)
                    if not info:
                        return DownloadResult(
                            success=False,
                            error="无法提取视频信息"
                        )
                    
                    # 执行下载
                    ydl.download([video_url])
                    
                    # 获取文件路径
                    filename = ydl.prepare_filename(info)
                    
                    # 如果文件名不是mp4，找到实际的mp4文件
                    if not filename.endswith('.mp4'):
                        base_name = os.path.splitext(filename)[0]
                        mp4_file = f"{base_name}.mp4"
                        if os.path.exists(mp4_file):
                            filename = mp4_file
                    
                    if os.path.exists(filename):
                        return DownloadResult(
                            success=True,
                            file_path=filename,
                            video_info=info
                        )
                    else:
                        return DownloadResult(
                            success=False,
                            error=f"下载文件未找到: {filename}"
                        )
                        
            except Exception as e:
                return DownloadResult(
                    success=False,
                    error=str(e)
                )
        
        # 在线程池中运行同步下载
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _download)
    
    async def download_video(self, video_info: VideoInfo) -> bool:
        """下载单个视频."""
        async with self._semaphore:
            try:
                # 更新状态为下载中
                await self.db.update_video_status(video_info.id, "downloading")
                
                # 发送开始下载通知
                await self.telegram.notify_download_start(video_info)
                
                # 执行下载
                result = await self._run_ytdlp(video_info.url)
                
                if result.success:
                    # 下载成功
                    await self.db.update_video_status(
                        video_info.id, 
                        "downloaded", 
                        file_path=result.file_path
                    )
                    
                    # 更新视频信息
                    video_info.status = "downloaded"
                    video_info.file_path = result.file_path
                    
                    # 发送完成通知
                    await self.telegram.notify_download_complete(video_info)
                    
                    # 触发回调
                    if self._download_complete_callback:
                        try:
                            await self._download_complete_callback()
                        except Exception as e:
                            print(f"下载完成回调执行失败: {str(e)}")
                    
                    return True
                else:
                    # 下载失败
                    await self.db.update_video_status(
                        video_info.id, 
                        "failed", 
                        error_message=result.error
                    )
                    await self.db.increment_retry_count(video_info.id)
                    
                    # 发送失败通知
                    await self.telegram.notify_download_failed(video_info, result.error)
                    
                    return False
                    
            except Exception as e:
                # 处理异常
                error_msg = f"下载异常: {str(e)}"
                await self.db.update_video_status(
                    video_info.id, 
                    "failed", 
                    error_message=error_msg
                )
                await self.db.increment_retry_count(video_info.id)
                
                # 发送失败通知
                await self.telegram.notify_download_failed(video_info, error_msg)
                
                return False
    
    async def retry_download(self, video_id: str) -> bool:
        """重试下载."""
        video_info = await self.db.get_video(video_id)
        if not video_info:
            print(f"视频不存在: {video_id}")
            return False
        
        # 检查重试次数
        if video_info.retry_count >= 3:
            await self.telegram.send_message(
                f"❌ 视频 {video_info.title} 重试次数已达上限，跳过下载"
            )
            return False
        
        # 重置状态并重试
        await self.db.update_video_status(video_id, "pending")
        return await self.download_video(video_info)
    
    async def process_download_queue(self) -> None:
        """处理下载队列."""
        pending_videos = await self.db.get_videos_by_status("pending")
        
        if not pending_videos:
            return
        
        print(f"开始处理 {len(pending_videos)} 个待下载视频")
        
        # 创建下载任务
        tasks = []
        for video in pending_videos:
            task = asyncio.create_task(self.download_video(video))
            tasks.append(task)
        
        # 等待所有下载完成
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def cleanup_old_files(self, max_age_hours: int = 24) -> None:
        """清理旧的下载文件."""
        if not os.path.exists(self.config.download_path):
            return
        
        import time
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        try:
            for filename in os.listdir(self.config.download_path):
                file_path = os.path.join(self.config.download_path, filename)
                
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    
                    if file_age > max_age_seconds:
                        os.remove(file_path)
                        print(f"清理旧文件: {filename}")
                        
        except Exception as e:
            print(f"清理文件时出错: {e}")
    
    async def get_download_info(self, video_url: str) -> Optional[Dict[str, Any]]:
        """获取视频信息（不下载）."""
        def _extract_info():
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    return ydl.extract_info(video_url, download=False)
            except Exception as e:
                print(f"提取视频信息失败: {e}")
                return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract_info)
    
    async def validate_video_url(self, video_url: str) -> bool:
        """验证视频URL是否有效."""
        info = await self.get_download_info(video_url)
        return info is not None