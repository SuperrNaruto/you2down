"""任务调度器模块."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Set
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import Settings
from database import Database, PlaylistInfo, DriveFileInfo
from youtube_client import YouTubeClient, YouTubeVideo
from downloader import VideoDownloader
from uploader import VideoUploader
from telegram_bot import TelegramNotifier
from instagram_client import InstagramClient, InstagramMedia
from instagram_downloader import InstagramDownloader


class TaskScheduler:
    """事件驱动任务调度器."""
    
    def __init__(
        self,
        config: Settings,
        database: Database,
        youtube_client: YouTubeClient,
        downloader: VideoDownloader,
        uploader: VideoUploader,
        telegram: TelegramNotifier,
        gdrive_handler=None
    ):
        """初始化调度器."""
        self.config = config
        self.db = database
        self.youtube = youtube_client
        self.downloader = downloader
        self.uploader = uploader
        self.telegram = telegram
        
        # 统一的Google Drive处理器
        self.gdrive_handler = gdrive_handler
        
        # Instagram相关组件
        self.instagram_client = None
        self.instagram_downloader = None
        
        # 创建调度器
        self.scheduler = AsyncIOScheduler()
        self._running = False
        
        # 事件驱动相关
        self._processing_downloads = False
        self._processing_uploads = False
        self._processing_gdrive = False
        self._event_queue = asyncio.Queue()
        self._event_processor_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """启动调度器."""
        if self._running:
            return
        
        # 设置Telegram回调函数
        self.telegram.set_strategies_callback(self.get_strategies_info)
        self.telegram.set_set_strategy_callback(self.set_playlist_strategy_command)
        
        # 初始化Instagram组件（如果启用）
        await self._init_instagram_components()
        
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
        
        # Google Drive相关任务（如果启用）
        if self.config.enable_gdrive_download and self.gdrive_handler:
            # 备用Google Drive下载队列处理
            self.scheduler.add_job(
                self.gdrive_handler.process_pending_downloads,
                IntervalTrigger(seconds=900),  # 15分钟备用检查
                id="backup_process_gdrive",
                name="备用Google Drive下载队列处理",
                max_instances=1,
                coalesce=True
            )
            
            # 已下载文件的上传处理
            self.scheduler.add_job(
                self.gdrive_handler.process_downloaded_files,
                IntervalTrigger(seconds=600),  # 10分钟检查已下载文件
                id="process_gdrive_uploads",
                name="Google Drive文件上传处理",
                max_instances=1,
                coalesce=True
            )
            
            # Google Drive文件清理
            self.scheduler.add_job(
                self.gdrive_handler.cleanup_failed_files,
                IntervalTrigger(hours=12),  # 12小时
                id="cleanup_gdrive",
                name="Google Drive文件清理",
                max_instances=1,
                coalesce=True
            )
        
        # Instagram相关任务（如果启用）
        if self.config.enable_instagram:
            # Instagram收藏检查
            self.scheduler.add_job(
                self.check_instagram_saved,
                IntervalTrigger(seconds=self.config.instagram_check_interval),
                id="check_instagram_saved",
                name="检查Instagram收藏",
                max_instances=1,
                coalesce=True
            )
            
            # Instagram下载队列处理
            self.scheduler.add_job(
                self.process_instagram_downloads,
                IntervalTrigger(seconds=900),  # 15分钟备用检查
                id="backup_process_instagram",
                name="备用Instagram下载队列处理",
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
                
                elif event_type == "drive_download_needed":
                    # 需要处理Google Drive下载
                    print("📱 立即触发Google Drive下载处理")
                    await self._trigger_gdrive_processing()
                
                elif event_type == "gdrive_process_needed":
                    # 需要处理新视频的Google Drive链接
                    videos_data = event_data.get("videos", [])
                    print(f"🔗 开始处理 {len(videos_data)} 个视频的Google Drive链接")
                    await self._process_new_gdrive_links(videos_data)
                
                elif event_type == "gdrive_download_completed":
                    # Google Drive下载完成，检查是否还有待处理的任务
                    await self._check_pending_gdrive_tasks()
                    
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

    
    async def _trigger_gdrive_processing(self) -> None:
        """触发Google Drive下载处理."""
        if not self.config.enable_gdrive_download or not self.gdrive_handler:
            return
        
        if not self._processing_gdrive:
            print("🔗 触发Google Drive下载队列处理")
            self._processing_gdrive = True
            try:
                await self.gdrive_handler.process_pending_downloads()
            finally:
                self._processing_gdrive = False
        else:
            print("Google Drive下载正在进行，跳过触发")
    
    async def _process_new_gdrive_links(self, videos_data: List[Dict]) -> None:
        """处理新视频的Google Drive链接."""
        if not self.config.enable_gdrive_download or not self.gdrive_handler:
            return
        
        for video_data in videos_data:
            try:
                video_id = video_data["id"]
                video_title = video_data["title"]
                video_description = video_data.get("description", "")
                
                print(f"🔗 处理视频 {video_title} 的Google Drive链接")
                
                # 使用处理器处理Google Drive链接
                result = await self.gdrive_handler.process_video_gdrive_links(
                    video_id, video_description
                )
                
                if result.files_processed > 0:
                    print(f"✅ 处理完成: {video_title} - {result.files_processed} 个文件已添加到下载队列")
                else:
                    print(f"ℹ️ 无文件需要处理: {video_title}")
                    
            except Exception as e:
                logger.error(f"处理视频 {video_data.get('title', video_data.get('id', 'unknown'))} 的Google Drive链接失败: {e}")
        
        # 处理完成后触发下载
        await self._trigger_gdrive_processing()
    
    async def _check_pending_gdrive_tasks(self) -> None:
        """检查待处理的Google Drive任务."""
        if not self.config.enable_gdrive_download or not self.gdrive_handler:
            return
        
        try:
            pending_files = await self.db.get_pending_drive_files()
            if pending_files:
                print(f"发现 {len(pending_files)} 个待处理的Google Drive文件")
                await self._trigger_gdrive_processing()
        except Exception as e:
            print(f"检查待处理Google Drive任务时出错: {e}")
    
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
            # 获取播放列表信息和下载策略
            playlist_info = await self.db.get_playlist_info(playlist_id)
            last_checked = playlist_info.last_checked if playlist_info else None
            
            # 获取播放列表的下载策略
            current_strategy = await self.db.get_playlist_strategy(playlist_id)
            config_strategy = self.config.get_playlist_strategy(playlist_id)
            
            # 如果配置中的策略与数据库不同，更新数据库
            if current_strategy != config_strategy:
                await self.db.set_playlist_strategy(playlist_id, config_strategy)
                current_strategy = config_strategy
                print(f"更新播放列表 {playlist_id} 下载策略为: {current_strategy}")
            
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
            print(f"🔍 调试: 调用 get_new_videos, playlist_id={playlist_id}, last_checked={last_checked}")
            new_videos = await self.youtube.get_new_videos(playlist_id, last_checked)
            print(f"🔍 调试: get_new_videos 返回 {len(new_videos)} 个视频")
            
            if new_videos:
                print(f"播放列表 {playlist_id} 发现 {len(new_videos)} 个新视频（策略: {current_strategy}）")
                
                new_videos_count = 0
                video_download_needed = False
                gdrive_download_needed = False
                
                # 根据策略处理新视频
                for video in new_videos:
                    # 检查是否已存在
                    if not await self.db.video_exists(video.id):
                        # 根据策略决定是否分析Google Drive链接
                        gdrive_links = []
                        if current_strategy in ['both', 'gdrive_only'] and self.gdrive_handler:
                            gdrive_links = await self.gdrive_handler.detect_links(video.description or "")
                        
                        # 设置Drive相关信息
                        if gdrive_links:
                            gdrive_links_data = [
                                {
                                    'file_id': link.file_id,
                                    'original_url': link.original_url,
                                    'link_type': link.link_type
                                } for link in gdrive_links
                            ]
                            video.gdrive_links = json.dumps(gdrive_links_data, ensure_ascii=False)
                            video.gdrive_status = "detected"
                            video.gdrive_file_count = len(gdrive_links)
                            print(f"检测到 {len(gdrive_links)} 个Google Drive链接: {video.title}")
                        else:
                            video.gdrive_status = "none"
                            video.gdrive_file_count = 0
                        
                        # 根据策略设置视频状态
                        if current_strategy == 'gdrive_only':
                            # 仅下载Drive文件，跳过视频下载
                            video.status = "skipped_video"
                        elif current_strategy == 'video_only':
                            # 仅下载视频，忽略Drive链接
                            video.status = "pending"
                            video.gdrive_status = "ignored"
                        else:  # both
                            video.status = "pending"
                        
                        await self.db.add_video(video)
                        print(f"添加新视频: {video.title} (策略: {current_strategy})")
                        new_videos_count += 1
                        
                        # 决定是否需要触发下载事件
                        if current_strategy in ['both', 'video_only']:
                            video_download_needed = True
                        
                        # 如果启用了Google Drive下载且策略允许，标记需要处理Google Drive链接
                        if (self.config.enable_gdrive_download and 
                            current_strategy in ['both', 'gdrive_only'] and 
                            gdrive_links and self.gdrive_handler):
                            gdrive_download_needed = True
                
                # 只在有新视频时发送通知（优先发送，避免阻塞）
                if new_videos_count > 0:
                    strategy_desc = self._get_strategy_description(current_strategy)
                    await self.telegram.notify_playlist_check_with_strategy(
                        playlist_id, playlist_name, new_videos_count, strategy_desc
                    )
                    
                    # 根据策略触发相应的下载事件
                    if video_download_needed:
                        print(f"🎯 触发视频下载事件，数量: {new_videos_count}")
                        await self._trigger_event("new_videos_found", {
                            "count": new_videos_count, 
                            "playlist_id": playlist_id,
                            "strategy": current_strategy
                        })
                    
                    # 异步触发Google Drive处理事件（不阻塞当前流程）
                    if gdrive_download_needed:
                        # 收集需要处理Google Drive链接的视频
                        gdrive_videos = [v for v in new_videos if v.gdrive_links and v.gdrive_status == "detected"]
                        
                        if gdrive_videos:
                            print(f"🔗 触发Google Drive处理事件，待处理视频: {len(gdrive_videos)} 个")
                            await self._trigger_event("gdrive_process_needed", {
                                "videos": [{"id": v.id, "title": v.title, "description": v.description} for v in gdrive_videos],
                                "playlist_id": playlist_id
                            })
            else:
                print(f"播放列表 {playlist_id} 无新视频（策略: {current_strategy}）")
                # 不发送通知
            
            # 更新播放列表检查时间和策略
            playlist_info = PlaylistInfo(
                id=playlist_id,
                title=playlist_name,  # 确保保存播放列表名称
                last_checked=datetime.now(timezone.utc),
                last_video_count=len(new_videos) if new_videos else 0,
                download_strategy=current_strategy
            )
            await self.db.update_playlist_info(playlist_info)
            
        except Exception as e:
            error_msg = f"检查播放列表 {playlist_id} 时出错: {str(e)}"
            print(error_msg)
            await self.telegram.notify_error("播放列表检查", error_msg)
    
    def _get_strategy_description(self, strategy: str) -> str:
        """获取策略描述."""
        strategy_map = {
            'both': '视频+Drive文件',
            'video_only': '仅视频',
            'gdrive_only': '仅Drive文件'
        }
        return strategy_map.get(strategy, strategy)
    
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

    
    async def get_strategies_info(self) -> str:
        """获取播放列表策略信息."""
        try:
            strategies = await self.db.get_all_playlist_strategies()
            if not strategies:
                return "📋 暂无播放列表策略配置"
            
            message = "📋 播放列表下载策略\n\n"
            
            strategy_names = {
                'both': '视频+Drive文件',
                'video_only': '仅视频',
                'gdrive_only': '仅Drive文件'
            }
            
            for playlist_id, strategy in strategies.items():
                # 获取播放列表名称
                playlist_info = await self.db.get_playlist_info(playlist_id)
                playlist_name = playlist_info.title if playlist_info and playlist_info.title else playlist_id
                
                strategy_desc = strategy_names.get(strategy, strategy)
                message += f"📂 {playlist_name}\n"
                message += f"   ID: {playlist_id}\n"
                message += f"   策略: {strategy_desc}\n\n"
            
            return message.strip()
            
        except Exception as e:
            return f"❌ 获取策略信息失败: {str(e)}"
    
    async def set_playlist_strategy_command(self, playlist_id: str, strategy: str) -> bool:
        """通过命令设置播放列表策略."""
        try:
            # 验证播放列表是否存在于配置中
            playlist_ids = self.config.get_playlists_list()
            if playlist_id not in playlist_ids:
                return False
            
            # 设置策略
            await self.db.set_playlist_strategy(playlist_id, strategy)
            print(f"通过Telegram命令设置播放列表 {playlist_id} 策略为: {strategy}")
            return True
            
        except Exception as e:
            print(f"设置播放列表策略失败: {e}")
            return False

    
    
    # Instagram相关方法
    
    async def _init_instagram_components(self) -> None:
        """初始化Instagram组件."""
        if not self.config.enable_instagram:
            print("Instagram功能已禁用")
            return
            
        try:
            # 初始化Instagram客户端
            self.instagram_client = InstagramClient(
                username=self.config.instagram_username,
                password=self.config.instagram_password,
                session_file=self.config.instagram_session_file,
                max_retries=self.config.instagram_max_retries,
                retry_delay=self.config.instagram_retry_delay,
                use_proxy=self.config.instagram_use_proxy,
                proxy_host=self.config.instagram_proxy_host,
                proxy_port=self.config.instagram_proxy_port,
                custom_user_agent=self.config.instagram_custom_user_agent,
                request_delay=self.config.instagram_request_delay,
                rate_limit_window=self.config.instagram_rate_limit_window
            )
            await self.instagram_client.init()
            
            # 初始化Instagram下载器
            self.instagram_downloader = InstagramDownloader(
                download_path=self.config.instagram_download_path,
                max_concurrent=self.config.max_instagram_concurrent,
                quality=self.config.instagram_quality
            )
            
            # 设置下载器回调
            self.instagram_downloader.set_callbacks(
                progress_callback=self._instagram_progress_callback,
                complete_callback=self._instagram_complete_callback,
                error_callback=self._instagram_error_callback
            )
            
            # 显示初始化信息
            proxy_info = f"IP轮换: {'\u5f00' if self.config.instagram_enable_ip_rotation else '\u5173'}"
            if proxy_list:
                proxy_info += f", 代理数量: {len(proxy_list)}"
            
            print(f"Instagram组件初始化完成 - 用户: {self.config.instagram_username}, {proxy_info}")
            
        except Exception as e:
            print(f"Instagram组件初始化失败: {e}")
            # 禁用Instagram功能
            self.config.enable_instagram = False
    
    async def check_instagram_saved(self) -> None:
        """检查Instagram收藏内容."""
        if not self.config.enable_instagram or not self.instagram_client:
            return
            
        try:
            print("开始检查Instagram收藏内容...")
            
            # 获取收藏的媒体
            saved_media = await self.instagram_client.get_saved_media(limit=50)
            
            new_media_count = 0
            
            # 处理每个媒体
            for media in saved_media:
                # 添加到数据库（如果不存在）
                try:
                    await self.db.add_instagram_media(
                        media_id=media.id,
                        shortcode=media.shortcode,
                        url=media.url,
                        username=media.username,
                        caption=media.caption,
                        timestamp=media.timestamp
                    )
                    new_media_count += 1
                    print(f"发现新的Instagram视频: {media.shortcode}")
                    
                except Exception:
                    # 媒体已存在，跳过
                    continue
            
            # 记录检查结果
            await self.db.record_instagram_check(
                username=self.config.instagram_username,
                media_count=len(saved_media),
                new_media_count=new_media_count
            )
            
            if new_media_count > 0:
                await self.telegram.send_message(
                    f"📸 发现 {new_media_count} 个新的Instagram收藏视频，已加入下载队列"
                )
                # 立即处理下载队列
                await self.process_instagram_downloads()
            else:
                print("没有新的Instagram收藏视频")
                
        except Exception as e:
            error_msg = f"检查Instagram收藏失败: {e}"
            print(error_msg)
            await self.telegram.send_message(f"❌ {error_msg}")
    
    async def process_instagram_downloads(self) -> None:
        """处理Instagram下载队列."""
        if not self.config.enable_instagram or not self.instagram_downloader:
            return
            
        try:
            # 获取待下载的媒体
            pending_media = await self.db.get_instagram_media_by_status('pending')
            
            if not pending_media:
                return
                
            print(f"开始处理 {len(pending_media)} 个Instagram下载任务")
            
            # 转换为InstagramMedia对象
            media_objects = []
            for media_data in pending_media:
                media = InstagramMedia({
                    'id': media_data['id'],
                    'shortcode': media_data['shortcode'],
                    'media_type': 2,  # video
                    'caption': {'text': media_data['caption']} if media_data['caption'] else None,
                    'taken_at': media_data['timestamp'].timestamp() if hasattr(media_data['timestamp'], 'timestamp') else 0,
                    'user': {'username': media_data['username']}
                })
                media_objects.append(media)
            
            # 批量下载
            downloaded_files = await self.instagram_downloader.download_batch(media_objects)
            
            print(f"Instagram下载完成，成功下载 {len(downloaded_files)} 个文件")
            
        except Exception as e:
            print(f"处理Instagram下载队列失败: {e}")
    
    def _instagram_progress_callback(self, shortcode: str, progress: Dict) -> None:
        """Instagram下载进度回调."""
        try:
            if progress.get('status') == 'downloading':
                percent = progress.get('_percent_str', 'N/A')
                print(f"Instagram下载进度 {shortcode}: {percent}")
        except Exception as e:
            print(f"处理Instagram下载进度时出错: {e}")
    
    async def _instagram_complete_callback(self, shortcode: str, file_path: str) -> None:
        """Instagram下载完成回调."""
        try:
            # 更新数据库状态
            await self.db.update_instagram_media_status(
                shortcode=shortcode,
                status='downloaded',
                file_path=file_path
            )
            
            # 如果启用了上传到Alist，执行上传
            if self.config.instagram_upload_to_alist:
                await self._upload_instagram_to_alist(shortcode, file_path)
            
            # 发送通知
            media_data = await self.db.get_instagram_media_by_status('downloaded')
            for media in media_data:
                if media['shortcode'] == shortcode:
                    await self.telegram.send_message(
                        f"📸 Instagram视频下载完成\n"
                        f"用户: @{media['username']}\n"
                        f"文件: {file_path}"
                    )
                    break
                    
        except Exception as e:
            print(f"处理Instagram下载完成回调时出错: {e}")
    
    async def _instagram_error_callback(self, shortcode: str, error: str) -> None:
        """Instagram下载错误回调."""
        try:
            # 增加重试次数
            await self.db.increment_instagram_retry(shortcode)
            
            # 更新错误状态
            await self.db.update_instagram_media_status(
                shortcode=shortcode,
                status='failed',
                error_message=error
            )
            
            print(f"Instagram下载失败 {shortcode}: {error}")
            
        except Exception as e:
            print(f"处理Instagram下载错误回调时出错: {e}")
    
    async def _upload_instagram_to_alist(self, shortcode: str, local_path: str) -> None:
        """将Instagram视频上传到Alist."""
        try:
            import os
            filename = os.path.basename(local_path)
            remote_path = f"{self.config.alist_path}/instagram/{filename}"
            
            # 上传文件
            success = await self.uploader.upload_file(local_path, remote_path)
            
            if success:
                print(f"成功上传Instagram视频到Alist: {remote_path}")
                
                # 更新数据库状态
                await self.db.update_instagram_media_status(
                    shortcode=shortcode,
                    status='completed'
                )
                
                # 清理本地文件
                try:
                    os.remove(local_path)
                    print(f"已清理本地Instagram文件: {local_path}")
                except Exception as e:
                    print(f"清理本地Instagram文件失败: {e}")
                    
                # 发送通知
                await self.telegram.send_message(
                    f"☁️ Instagram视频已上传到云存储\n"
                    f"路径: {remote_path}"
                )
            else:
                print(f"上传Instagram视频到Alist失败: {local_path}")
                await self.db.update_instagram_media_status(
                    shortcode=shortcode,
                    status='upload_failed',
                    error_message="上传到Alist失败"
                )
                
        except Exception as e:
            print(f"上传Instagram视频到Alist时出错: {e}")
            await self.db.update_instagram_media_status(
                shortcode=shortcode,
                status='upload_failed',
                error_message=str(e)
            )
