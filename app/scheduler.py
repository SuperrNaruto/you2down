"""任务调度器模块."""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Set
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import Settings
from database import Database, PlaylistInfo
from youtube_client import YouTubeClient
from downloader import VideoDownloader
from uploader import VideoUploader
from telegram_bot import TelegramNotifier


class TaskScheduler:
    """事件驱动任务调度器."""
    
    def __init__(
        self,
        config: Settings,
        database: Database,
        youtube_client: YouTubeClient,
        downloader: VideoDownloader,
        uploader: VideoUploader,
        telegram: TelegramNotifier
    ):
        """初始化调度器."""
        self.config = config
        self.db = database
        self.youtube = youtube_client
        self.downloader = downloader
        self.uploader = uploader
        self.telegram = telegram
        
        # 创建调度器
        self.scheduler = AsyncIOScheduler()
        self._running = False
        
        # 事件驱动相关
        self._processing_downloads = False
        self._processing_uploads = False
        self._event_queue = asyncio.Queue()
        self._event_processor_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """启动调度器."""
        if self._running:
            return
        
        # 添加定时任务
        self._add_scheduled_jobs()
        
        # 启动事件处理器
        self._event_processor_task = asyncio.create_task(self._process_events())
        
        # 启动调度器
        self.scheduler.start()
        self._running = True
        
        print("事件驱动任务调度器已启动")
        await self.telegram.send_message("⏰ 事件驱动任务调度器已启动，开始监控播放列表")
        
        # 立即执行一次检查
        await self.check_all_playlists()
    
    async def stop(self) -> None:
        """停止调度器."""
        if not self._running:
            return
        
        # 停止事件处理器
        if self._event_processor_task:
            self._event_processor_task.cancel()
            try:
                await self._event_processor_task
            except asyncio.CancelledError:
                pass
        
        self.scheduler.shutdown()
        self._running = False
        
        print("事件驱动任务调度器已停止")
        await self.telegram.send_message("⏰ 事件驱动任务调度器已停止")
    
    def _add_scheduled_jobs(self) -> None:
        """添加定时任务."""
        
        # 主要任务：检查播放列表
        self.scheduler.add_job(
            self.check_all_playlists,
            IntervalTrigger(seconds=self.config.check_interval),
            id="check_playlists",
            name="检查播放列表",
            max_instances=1,
            coalesce=True
        )
        
        # 备用下载队列处理（防止事件驱动失效）
        self.scheduler.add_job(
            self.process_download_queue,
            IntervalTrigger(seconds=600),  # 10分钟备用检查
            id="backup_process_downloads",
            name="备用下载队列处理",
            max_instances=1,
            coalesce=True
        )
        
        # 备用上传队列处理（防止事件驱动失效）
        self.scheduler.add_job(
            self.process_upload_queue,
            IntervalTrigger(seconds=600),  # 10分钟备用检查
            id="backup_process_uploads",
            name="备用上传队列处理",
            max_instances=1,
            coalesce=True
        )
        
        # 清理任务
        self.scheduler.add_job(
            self.cleanup_task,
            IntervalTrigger(hours=6),  # 6小时
            id="cleanup",
            name="清理任务",
            max_instances=1,
            coalesce=True
        )
        
        # 每日统计报告
        self.scheduler.add_job(
            self.daily_report,
            IntervalTrigger(hours=24),  # 24小时
            id="daily_report",
            name="每日统计报告",
            max_instances=1,
            coalesce=True
        )
        
        # 重试失败任务
        self.scheduler.add_job(
            self.retry_failed_tasks,
            IntervalTrigger(hours=2),  # 2小时
            id="retry_failed",
            name="重试失败任务",
            max_instances=1,
            coalesce=True
        )
    
    async def _process_events(self) -> None:
        """处理事件队列."""
        print("事件处理器已启动")
        
        while self._running:
            try:
                # 等待事件，超时后继续循环
                try:
                    event = await asyncio.wait_for(self._event_queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    continue
                
                event_type = event.get("type")
                print(f"⚡ 开始处理事件: {event_type}")
                
                if event_type == "new_videos_found":
                    # 发现新视频，立即触发下载队列处理
                    print("🚀 立即触发下载队列处理")
                    await self._trigger_download_processing()
                    
                elif event_type == "download_completed":
                    # 下载完成，立即触发上传队列处理
                    await self._trigger_upload_processing()
                    
                elif event_type == "upload_completed":
                    # 上传完成，检查是否还有待处理的任务
                    await self._check_pending_tasks()
                    
                # 标记事件已处理
                self._event_queue.task_done()
                
            except Exception as e:
                print(f"处理事件时出错: {str(e)}")
                await asyncio.sleep(1)
    
    async def _trigger_event(self, event_type: str, data: Optional[Dict] = None) -> None:
        """触发事件."""
        event = {"type": event_type, "timestamp": datetime.now(), "data": data or {}}
        await self._event_queue.put(event)
        print(f"📨 事件已入队: {event_type}, 队列大小: {self._event_queue.qsize()}")
    
    async def _trigger_download_processing(self) -> None:
        """触发下载队列处理."""
        if self._processing_downloads:
            print("⏳ 下载队列正在处理中，跳过")
            return
        
        print("🔄 开始处理下载队列")
        self._processing_downloads = True
        try:
            await self.process_download_queue()
        finally:
            self._processing_downloads = False
            print("✅ 下载队列处理完成")
    
    async def _trigger_upload_processing(self) -> None:
        """触发上传队列处理."""
        if self._processing_uploads:
            print("上传队列正在处理中，跳过")
            return
        
        self._processing_uploads = True
        try:
            await self.process_upload_queue()
        finally:
            self._processing_uploads = False
    
    async def _check_pending_tasks(self) -> None:
        """检查是否还有待处理的任务."""
        try:
            # 检查是否还有待下载的视频
            pending_downloads = await self.db.get_videos_by_status("pending")
            if pending_downloads:
                await self._trigger_event("new_videos_found")
            
            # 检查是否还有待上传的视频
            downloaded_videos = await self.db.get_videos_by_status("downloaded")
            if downloaded_videos:
                await self._trigger_event("download_completed")
        except Exception as e:
            print(f"检查待处理任务时出错: {str(e)}")
    
    async def check_all_playlists(self) -> None:
        """检查所有播放列表."""
        try:
            print(f"开始检查播放列表: {datetime.now()}")
            
            for playlist_id in self.config.get_playlists_list():
                await self.check_playlist(playlist_id)
                
                # 避免API限制，短暂延迟
                await asyncio.sleep(2)
                
        except Exception as e:
            error_msg = f"检查播放列表时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("播放列表检查", error_msg)
    
    async def check_playlist(self, playlist_id: str) -> None:
        """检查单个播放列表."""
        try:
            # 获取播放列表信息
            playlist_info = await self.db.get_playlist_info(playlist_id)
            last_checked = playlist_info.last_checked if playlist_info else None
            
            # 如果数据库中没有播放列表名称，从YouTube API获取
            playlist_name = None
            if playlist_info and playlist_info.title:
                playlist_name = playlist_info.title
            else:
                # 从YouTube API获取播放列表信息
                yt_playlist_info = await self.youtube.get_playlist_info(playlist_id)
                if yt_playlist_info:
                    playlist_name = yt_playlist_info.title
                    # 更新数据库中的播放列表信息
                    await self.db.update_playlist_info(yt_playlist_info)
            
            # 如果仍然没有获取到名称，使用ID作为后备
            if not playlist_name:
                playlist_name = playlist_id
            
            # 获取新视频
            new_videos = await self.youtube.get_new_videos(playlist_id, last_checked)
            
            if new_videos:
                print(f"播放列表 {playlist_id} 发现 {len(new_videos)} 个新视频")
                
                new_videos_count = 0
                # 添加到数据库
                for video in new_videos:
                    # 检查是否已存在
                    if not await self.db.video_exists(video.id):
                        await self.db.add_video(video)
                        print(f"添加新视频: {video.title}")
                        new_videos_count += 1
                
                # 只在有新视频时发送通知
                if new_videos_count > 0:
                    await self.telegram.notify_playlist_check(playlist_id, playlist_name, new_videos_count)
                    # 触发事件：发现新视频
                    print(f"🎯 触发新视频事件，数量: {new_videos_count}")
                    await self._trigger_event("new_videos_found", {"count": new_videos_count, "playlist_id": playlist_id})
            else:
                print(f"播放列表 {playlist_id} 无新视频")
                # 不发送通知
            
            # 更新播放列表检查时间
            playlist_info = PlaylistInfo(
                id=playlist_id,
                title=playlist_name,  # 确保保存播放列表名称
                last_checked=datetime.now(timezone.utc),
                last_video_count=len(new_videos) if new_videos else 0
            )
            await self.db.update_playlist_info(playlist_info)
            
        except Exception as e:
            error_msg = f"检查播放列表 {playlist_id} 时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("播放列表检查", error_msg)
    
    async def process_download_queue(self) -> None:
        """处理下载队列."""
        try:
            await self.downloader.process_download_queue()
        except Exception as e:
            error_msg = f"处理下载队列时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("下载队列处理", error_msg)
    
    async def process_upload_queue(self) -> None:
        """处理上传队列."""
        try:
            await self.uploader.process_upload_queue()
        except Exception as e:
            error_msg = f"处理上传队列时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("上传队列处理", error_msg)
    
    async def cleanup_task(self) -> None:
        """清理任务."""
        try:
            print("开始执行清理任务")
            
            # 清理旧的下载文件
            await self.downloader.cleanup_old_files(max_age_hours=24)
            
            # 清理失败的上传文件
            await self.uploader.cleanup_failed_uploads()
            
            print("清理任务完成")
            
        except Exception as e:
            error_msg = f"清理任务时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("清理任务", error_msg)
    
    async def daily_report(self) -> None:
        """生成每日统计报告."""
        try:
            stats = await self.db.get_stats()
            await self.telegram.notify_daily_summary(stats.get("status_counts", {}))
        except Exception as e:
            error_msg = f"生成每日报告时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("每日报告", error_msg)
    
    async def retry_failed_tasks(self) -> None:
        """重试失败的任务."""
        try:
            failed_videos = await self.db.get_videos_by_status("failed")
            retry_count = 0
            
            for video in failed_videos:
                # 只重试3次以内的
                if video.retry_count < 3:
                    # 重置状态
                    if video.file_path:
                        # 有文件路径说明下载成功了，重试上传
                        await self.db.update_video_status(video.id, "downloaded")
                    else:
                        # 没有文件路径说明下载失败，重试下载
                        await self.db.update_video_status(video.id, "pending")
                    
                    retry_count += 1
            
            if retry_count > 0:
                print(f"重置 {retry_count} 个失败任务进行重试")
                await self.telegram.send_message(f"🔄 重置 {retry_count} 个失败任务进行重试")
                
        except Exception as e:
            error_msg = f"重试失败任务时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("重试失败任务", error_msg)
    
    async def add_video_manually(self, video_url: str, playlist_id: str = "manual") -> bool:
        """手动添加视频."""
        try:
            # 验证视频URL
            if not await self.downloader.validate_video_url(video_url):
                return False
            
            # 提取视频ID
            video_id = video_url.split("v=")[-1].split("&")[0]
            
            # 检查是否已存在
            if await self.db.video_exists(video_id):
                print(f"视频已存在: {video_id}")
                return False
            
            # 获取视频信息
            video_info = await self.youtube.get_video_info(video_id)
            if not video_info:
                return False
            
            # 创建视频记录
            from database import VideoInfo
            video_record = VideoInfo(
                id=video_id,
                title=video_info.title,
                url=video_url,
                playlist_id=playlist_id
            )
            
            # 添加到数据库
            await self.db.add_video(video_record)
            
            print(f"手动添加视频: {video_info.title}")
            await self.telegram.send_message(f"✅ 手动添加视频: {video_info.title}")
            
            return True
            
        except Exception as e:
            error_msg = f"手动添加视频失败: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("手动添加视频", error_msg)
            return False
    
    async def get_status(self) -> str:
        """获取系统状态."""
        try:
            stats = await self.db.get_stats()
            status_counts = stats.get("status_counts", {})
            
            status_text = (
                "📊 系统状态报告\n"
                f"🕐 运行状态: {'运行中' if self._running else '已停止'}\n"
                f"📈 总视频数: {stats.get('total_videos', 0)}\n"
                f"✅ 已完成: {status_counts.get('completed', 0)}\n"
                f"🔄 处理中: {status_counts.get('downloading', 0) + status_counts.get('uploading', 0)}\n"
                f"⏳ 待处理: {status_counts.get('pending', 0)}\n"
                f"❌ 失败: {status_counts.get('failed', 0)}\n"
                f"📋 播放列表数: {stats.get('total_playlists', 0)}\n"
                f"⏰ 最后检查: {datetime.now().strftime('%H:%M:%S')}"
            )
            
            return status_text
            
        except Exception as e:
            return f"❌ 获取状态失败: {str(e)}"