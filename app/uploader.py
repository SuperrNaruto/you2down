"""文件上传管理器模块."""

import os
import asyncio
from typing import Optional, Callable, Awaitable

from config import Settings
from database import VideoInfo, Database
from alist_client import AlistClient
from telegram_bot import TelegramNotifier


class VideoUploader:
    """视频上传管理器."""
    
    def __init__(
        self, 
        config: Settings,
        database: Database,
        alist_client: AlistClient,
        telegram: TelegramNotifier
    ):
        """初始化上传管理器."""
        self.config = config
        self.db = database
        self.alist = alist_client
        self.telegram = telegram
        self._semaphore = asyncio.Semaphore(2)  # 限制并发上传数
        self._upload_complete_callback: Optional[Callable[[], Awaitable[None]]] = None
        
    def set_upload_complete_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """设置上传完成回调."""
        self._upload_complete_callback = callback
    
    async def upload_video(self, video_info: VideoInfo) -> bool:
        """上传单个视频."""
        async with self._semaphore:
            try:
                if not video_info.file_path or not os.path.exists(video_info.file_path):
                    error_msg = f"文件不存在: {video_info.file_path}"
                    await self.db.update_video_status(
                        video_info.id, 
                        "failed", 
                        error_message=error_msg
                    )
                    await self.telegram.notify_upload_failed(video_info, error_msg)
                    return False
                
                # 更新状态为上传中
                await self.db.update_video_status(video_info.id, "uploading")
                
                # 发送开始上传通知
                await self.telegram.notify_upload_start(video_info)
                
                # 执行上传
                upload_result = await self.alist.upload_file(
                    video_info.file_path,
                    self.config.alist_path
                )
                
                if upload_result.success:
                    # 上传成功
                    await self.db.update_video_status(video_info.id, "completed")
                    
                    # 发送完成通知
                    await self.telegram.notify_upload_complete(
                        video_info, 
                        upload_result.file_url
                    )
                    
                    # 触发回调
                    if self._upload_complete_callback:
                        try:
                            await self._upload_complete_callback()
                        except Exception as e:
                            print(f"上传完成回调执行失败: {str(e)}")
                    
                    # 清理本地文件
                    await self._cleanup_local_file(video_info.file_path)
                    
                    return True
                else:
                    # 上传失败
                    error_msg = upload_result.error or "上传失败"
                    await self.db.update_video_status(
                        video_info.id, 
                        "failed", 
                        error_message=error_msg
                    )
                    await self.db.increment_retry_count(video_info.id)
                    
                    # 发送失败通知
                    await self.telegram.notify_upload_failed(video_info, error_msg)
                    
                    return False
                    
            except Exception as e:
                # 处理异常
                error_msg = f"上传异常: {str(e)}"
                await self.db.update_video_status(
                    video_info.id, 
                    "failed", 
                    error_message=error_msg
                )
                await self.db.increment_retry_count(video_info.id)
                
                # 发送失败通知
                await self.telegram.notify_upload_failed(video_info, error_msg)
                
                return False
    
    async def _cleanup_local_file(self, file_path: str) -> None:
        """清理本地文件."""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"清理本地文件: {file_path}")
                
                # 删除相关的信息文件
                info_file = f"{os.path.splitext(file_path)[0]}.info.json"
                if os.path.exists(info_file):
                    os.remove(info_file)
                    print(f"清理信息文件: {info_file}")
                    
        except Exception as e:
            print(f"清理文件失败: {e}")
    
    async def retry_upload(self, video_id: str) -> bool:
        """重试上传."""
        video_info = await self.db.get_video(video_id)
        if not video_info:
            print(f"视频不存在: {video_id}")
            return False
        
        # 检查重试次数
        if video_info.retry_count >= 3:
            await self.telegram.send_message(
                f"❌ 视频 {video_info.title} 重试次数已达上限，跳过上传"
            )
            return False
        
        # 如果是已下载状态，直接上传
        if video_info.status == "downloaded":
            return await self.upload_video(video_info)
        else:
            await self.telegram.send_message(
                f"❌ 视频 {video_info.title} 状态不正确: {video_info.status}"
            )
            return False
    
    async def process_upload_queue(self) -> None:
        """处理上传队列."""
        downloaded_videos = await self.db.get_videos_by_status("downloaded")
        
        if not downloaded_videos:
            return
        
        print(f"开始处理 {len(downloaded_videos)} 个待上传视频")
        
        # 创建上传任务
        tasks = []
        for video in downloaded_videos:
            task = asyncio.create_task(self.upload_video(video))
            tasks.append(task)
        
        # 等待所有上传完成
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def get_upload_stats(self) -> dict:
        """获取上传统计信息."""
        stats = await self.db.get_stats()
        return {
            "total_videos": stats.get("total_videos", 0),
            "completed": stats.get("status_counts", {}).get("completed", 0),
            "uploading": stats.get("status_counts", {}).get("uploading", 0),
            "downloaded": stats.get("status_counts", {}).get("downloaded", 0),
            "failed": stats.get("status_counts", {}).get("failed", 0),
            "pending": stats.get("status_counts", {}).get("pending", 0)
        }
    
    async def validate_upload_path(self) -> bool:
        """验证上传路径是否可用."""
        try:
            # 测试创建临时文件
            test_file = os.path.join(self.config.download_path, "test_upload.txt")
            with open(test_file, 'w') as f:
                f.write("test")
            
            # 测试上传
            result = await self.alist.upload_file(test_file, self.config.alist_path)
            
            # 清理测试文件
            if os.path.exists(test_file):
                os.remove(test_file)
            
            # 如果上传成功，删除远程测试文件
            if result.success:
                await self.alist.delete_file(f"{self.config.alist_path}/test_upload.txt")
            
            return result.success
            
        except Exception as e:
            print(f"验证上传路径失败: {e}")
            return False
    
    async def cleanup_failed_uploads(self) -> None:
        """清理上传失败的视频文件."""
        failed_videos = await self.db.get_videos_by_status("failed")
        
        for video in failed_videos:
            if video.file_path and os.path.exists(video.file_path):
                # 如果重试次数超过限制，清理本地文件
                if video.retry_count >= 3:
                    await self._cleanup_local_file(video.file_path)
                    print(f"清理失败视频文件: {video.title}")
    
    async def force_cleanup_downloads(self) -> None:
        """强制清理所有下载文件."""
        try:
            if os.path.exists(self.config.download_path):
                for filename in os.listdir(self.config.download_path):
                    file_path = os.path.join(self.config.download_path, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        print(f"强制清理文件: {filename}")
        except Exception as e:
            print(f"强制清理文件时出错: {e}")