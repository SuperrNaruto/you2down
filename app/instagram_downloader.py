"""Instagram视频下载器模块."""

import os
import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
import yt_dlp
from datetime import datetime

from instagram_client import InstagramMedia

logger = logging.getLogger(__name__)


class InstagramDownloader:
    """Instagram视频下载器."""
    
    def __init__(
        self,
        download_path: str,
        max_concurrent: int = 2,
        quality: str = "best"
    ):
        """
        初始化下载器.
        
        Args:
            download_path: 下载目录
            max_concurrent: 最大并发下载数
            quality: 视频质量
        """
        self.download_path = Path(download_path)
        self.max_concurrent = max_concurrent
        self.quality = quality
        
        # 创建下载目录
        self.download_path.mkdir(parents=True, exist_ok=True)
        
        # 并发控制
        self._semaphore = asyncio.Semaphore(max_concurrent)
        
        # 回调函数
        self.progress_callback: Optional[Callable[[str, Dict], None]] = None
        self.complete_callback: Optional[Callable[[str, str], None]] = None
        self.error_callback: Optional[Callable[[str, str], None]] = None
    
    def _get_quality_format(self) -> str:
        """获取质量格式字符串."""
        quality_map = {
            "best": "best[ext=mp4]",
            "720p": "best[height<=720][ext=mp4]/best[ext=mp4]",
            "480p": "best[height<=480][ext=mp4]/best[ext=mp4]",
            "worst": "worst[ext=mp4]"
        }
        return quality_map.get(self.quality, quality_map["best"])
    
    def _get_output_filename(self, media: InstagramMedia) -> str:
        """生成输出文件名."""
        # 清理标题用作文件名
        title = media.caption[:50] if media.caption else "instagram_video"
        title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        title = title.replace(' ', '_')
        
        if not title:
            title = f"instagram_{media.shortcode}"
        
        timestamp = media.timestamp.strftime("%Y%m%d")
        return f"{timestamp}_{media.username}_{title}_{media.shortcode}"
    
    async def download_media(self, media: InstagramMedia) -> Optional[str]:
        """
        下载单个Instagram媒体.
        
        Args:
            media: Instagram媒体对象
            
        Returns:
            下载的文件路径，失败返回None
        """
        async with self._semaphore:
            return await self._download_single(media)
    
    async def _download_single(self, media: InstagramMedia) -> Optional[str]:
        """下载单个媒体文件."""
        try:
            if not media.is_video:
                logger.warning(f"跳过非视频媒体: {media.shortcode}")
                return None
            
            # 生成输出文件名
            output_filename = self._get_output_filename(media)
            
            # 检查文件是否已存在
            existing_files = list(self.download_path.glob(f"{output_filename}.*"))
            if existing_files:
                logger.info(f"文件已存在，跳过下载: {existing_files[0].name}")
                return str(existing_files[0])
            
            # 配置yt-dlp选项
            ydl_opts = {
                'outtmpl': str(self.download_path / f"{output_filename}.%(ext)s"),
                'format': self._get_quality_format(),
                'writeinfojson': False,
                'writesubtitles': False,
                'writeautomaticsub': False,
                'ignoreerrors': False,
                'no_warnings': False,
                'extractaudio': False,
                'audioformat': 'mp3',
                'embed_subs': False,
                'writesubtitles': False,
                'writethumbnail': False,
                'geo_bypass': True,
                'nocheckcertificate': True,
            }
            
            # 添加进度回调
            if self.progress_callback:
                def progress_hook(d):
                    if d['status'] == 'downloading':
                        self.progress_callback(media.shortcode, d)
                ydl_opts['progress_hooks'] = [progress_hook]
            
            logger.info(f"开始下载Instagram视频: {media.url}")
            
            # 在线程池中执行下载
            loop = asyncio.get_event_loop()
            downloaded_file = await loop.run_in_executor(
                None, 
                self._download_with_ytdlp, 
                media.url, 
                ydl_opts
            )
            
            if downloaded_file:
                logger.info(f"Instagram视频下载完成: {downloaded_file}")
                if self.complete_callback:
                    self.complete_callback(media.shortcode, downloaded_file)
                return downloaded_file
            else:
                logger.error(f"下载失败: {media.url}")
                if self.error_callback:
                    self.error_callback(media.shortcode, "下载失败")
                return None
                
        except Exception as e:
            error_msg = f"下载Instagram视频失败 {media.shortcode}: {e}"
            logger.error(error_msg)
            if self.error_callback:
                self.error_callback(media.shortcode, str(e))
            return None
    
    def _download_with_ytdlp(self, url: str, ydl_opts: Dict) -> Optional[str]:
        """使用yt-dlp下载视频."""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 提取信息
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None
                
                # 获取预期的文件名
                filename = ydl.prepare_filename(info)
                
                # 下载视频
                ydl.download([url])
                
                # 检查文件是否存在
                if os.path.exists(filename):
                    return filename
                else:
                    # 尝试找到实际下载的文件
                    base_name = os.path.splitext(filename)[0]
                    for ext in ['.mp4', '.webm', '.mkv', '.avi']:
                        potential_file = f"{base_name}{ext}"
                        if os.path.exists(potential_file):
                            return potential_file
                    return None
                    
        except Exception as e:
            logger.error(f"yt-dlp下载失败: {e}")
            return None
    
    async def download_batch(self, media_list: List[InstagramMedia]) -> List[str]:
        """
        批量下载媒体文件.
        
        Args:
            media_list: 媒体列表
            
        Returns:
            成功下载的文件路径列表
        """
        logger.info(f"开始批量下载 {len(media_list)} 个Instagram视频")
        
        # 创建下载任务
        tasks = []
        for media in media_list:
            if media.is_video:
                task = self.download_media(media)
                tasks.append(task)
        
        if not tasks:
            logger.warning("没有可下载的视频")
            return []
        
        # 并发执行下载
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 收集成功下载的文件
        downloaded_files = []
        for result in results:
            if isinstance(result, str) and result:
                downloaded_files.append(result)
            elif isinstance(result, Exception):
                logger.error(f"下载任务异常: {result}")
        
        logger.info(f"批量下载完成，成功下载 {len(downloaded_files)} 个文件")
        return downloaded_files
    
    def set_callbacks(
        self,
        progress_callback: Optional[Callable[[str, Dict], None]] = None,
        complete_callback: Optional[Callable[[str, str], None]] = None,
        error_callback: Optional[Callable[[str, str], None]] = None
    ) -> None:
        """设置回调函数."""
        self.progress_callback = progress_callback
        self.complete_callback = complete_callback
        self.error_callback = error_callback
    
    def get_stats(self) -> Dict[str, Any]:
        """获取下载器统计信息."""
        download_dir = Path(self.download_path)
        
        if not download_dir.exists():
            return {
                'total_files': 0,
                'total_size': 0,
                'download_path': str(download_dir)
            }
        
        video_files = []
        for ext in ['.mp4', '.webm', '.mkv', '.avi']:
            video_files.extend(download_dir.glob(f'*{ext}'))
        
        total_size = sum(f.stat().st_size for f in video_files if f.exists())
        
        return {
            'total_files': len(video_files),
            'total_size': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'download_path': str(download_dir)
        }