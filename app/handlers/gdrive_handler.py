"""Google Drive文件处理器 - 统一生命周期管理."""

import asyncio
import logging
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from gdrive_detector import GoogleDriveDetector, DriveLink
from gdrive_downloader import GoogleDriveDownloader
from database import Database, DriveFileInfo
from core.file_uploader import UnifiedFileUploader, FileInfo, UploadStatus

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    """处理结果."""
    success: bool
    message: str
    files_processed: int = 0
    files_uploaded: int = 0
    errors: List[str] = None


class GoogleDriveHandler:
    """Google Drive文件处理器 - 完整生命周期管理."""
    
    def __init__(
        self, 
        config, 
        database: Database, 
        alist_client, 
        telegram_notifier=None
    ):
        """初始化Google Drive处理器."""
        self.config = config
        self.db = database
        self.alist = alist_client
        self.telegram = telegram_notifier
        
        # 初始化组件
        self.detector = GoogleDriveDetector()
        self.downloader = None  # 延迟初始化
        self.uploader = UnifiedFileUploader(
            alist_client=alist_client,
            database=database,
            telegram_notifier=telegram_notifier
        )
        
        # 处理统计
        self.stats = {
            "links_detected": 0,
            "files_downloaded": 0,
            "files_uploaded": 0,
            "errors": 0
        }
    
    async def _ensure_downloader(self):
        """确保下载器已初始化."""
        if self.downloader is None:
            self.downloader = GoogleDriveDownloader(
                download_path=self.config.gdrive_download_path,
                max_concurrent=self.config.max_gdrive_concurrent,
                max_file_size=self.config.max_gdrive_file_size
            )
            await self.downloader.start()
    
    async def detect_links(self, description: str) -> List[DriveLink]:
        """从描述中检测Google Drive链接."""
        try:
            links = self.detector.detect_drive_links(description)
            self.stats["links_detected"] += len(links)
            
            if links:
                logger.info(f"检测到 {len(links)} 个Google Drive链接")
                for link in links:
                    logger.debug(f"  - 文件ID: {link.file_id}, 类型: {link.link_type}")
            
            return links
        except Exception as e:
            logger.error(f"检测Google Drive链接失败: {e}")
            return []
    
    async def _create_drive_file_record(
        self, 
        video_id: str, 
        drive_link: DriveLink
    ) -> DriveFileInfo:
        """创建Google Drive文件记录."""
        file_id = drive_link.file_id
        
        # 尝试获取真实文件名
        real_filename = await self._get_real_filename(drive_link)
        filename = real_filename or f"gdrive_{file_id}"
        
        drive_file = DriveFileInfo(
            id=f"{video_id}_{file_id}",
            video_id=video_id,
            file_id=file_id,
            filename=filename,
            original_url=drive_link.original_url,
            link_type=drive_link.link_type,
            status="pending",
            file_path=None,
            file_size=None,
            error_message=None,
            retry_count=0,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        await self.db.add_drive_file(drive_file)
        logger.info(f"创建Google Drive文件记录: {filename} ({file_id})")
        
        return drive_file
    
    async def _get_real_filename(self, drive_link: DriveLink) -> Optional[str]:
        """尝试获取Google Drive文件的真实文件名."""
        try:
            await self._ensure_downloader()
            
            # 获取下载信息（包含真实文件名）
            download_info = await self.downloader._get_download_info(drive_link)
            
            if download_info['success'] and download_info.get('filename'):
                real_filename = download_info['filename']
                logger.info(f"获取到真实文件名: {real_filename} (文件ID: {drive_link.file_id})")
                return real_filename
            else:
                logger.warning(f"无法获取真实文件名: {download_info.get('error', '未知原因')} (文件ID: {drive_link.file_id})")
                return None
                
        except Exception as e:
            logger.warning(f"获取真实文件名时出错: {e} (文件ID: {drive_link.file_id})")
            return None
    
    async def download_file(self, drive_file: DriveFileInfo) -> bool:
        """下载单个Google Drive文件."""
        try:
            await self._ensure_downloader()
            
            # 更新状态为下载中
            await self.db.update_drive_file_status(
                drive_file.file_id, 'downloading'
            )
            
            # 创建DriveLink对象
            drive_link = DriveLink(
                file_id=drive_file.file_id,
                original_url=drive_file.original_url,
                link_type=drive_file.link_type
            )
            
            # 下载文件
            result = await self.downloader.download_file(drive_link, drive_file.filename)
            
            if result['success']:
                # 更新成功状态
                await self.db.update_drive_file_status(
                    drive_file.file_id,
                    'downloaded',  # 注意：这里改为downloaded，区别于completed
                    result['file_path'],
                    result['file_size']
                )
                
                self.stats["files_downloaded"] += 1
                logger.info(f"成功下载Google Drive文件: {drive_file.filename} ({result['file_size']/1024/1024:.1f}MB)")
                
                # 发送下载成功通知
                if self.telegram:
                    await self.telegram.notify_gdrive_download_success(
                        drive_file.video_id, 
                        drive_file.filename, 
                        result['file_size']
                    )
                
                return True
            else:
                await self._handle_download_error(drive_file, result['error'])
                return False
                
        except Exception as e:
            await self._handle_download_error(drive_file, str(e))
            return False
    
    async def _handle_download_error(self, drive_file: DriveFileInfo, error_message: str):
        """处理下载错误."""
        logger.error(f"Google Drive文件下载失败: {drive_file.filename} - {error_message}")
        self.stats["errors"] += 1
        
        # 增加重试次数
        retry_count = drive_file.retry_count + 1
        
        if retry_count >= 3:
            # 超过重试次数，标记为失败
            await self.db.update_drive_file_status(
                drive_file.file_id, 
                'failed', 
                error_message=error_message
            )
            
            # 发送失败通知
            if self.telegram:
                await self.telegram.notify_gdrive_download_failed(
                    drive_file.video_id, 
                    drive_file.filename, 
                    error_message
                )
        else:
            # 重置为pending状态等待重试
            await self.db.update_drive_file_status(
                drive_file.file_id, 
                'pending', 
                error_message=error_message
            )
            # 更新重试次数
            await self.db.increment_drive_file_retry(drive_file.file_id)
    
    async def upload_file(self, drive_file: DriveFileInfo) -> bool:
        """上传Google Drive文件到Alist."""
        if not self.config.gdrive_upload_to_alist:
            logger.info(f"Google Drive文件上传已禁用，跳过: {drive_file.filename}")
            return True
        
        try:
            # 构建本地路径和远程路径
            local_path = drive_file.file_path
            if not local_path:
                logger.error(f"文件路径为空: {drive_file.filename}")
                return False
            
            # 转换容器路径到主机路径（如果需要）
            if local_path.startswith('/app/'):
                local_path = local_path.replace('/app/', './')
            
            if not os.path.exists(local_path):
                logger.error(f"本地文件不存在: {local_path}")
                return False
            
            # 构建远程路径
            filename = os.path.basename(local_path)
            remote_path = f"{self.config.alist_path}/gdrive/{filename}"
            
            logger.info(f"开始上传Google Drive文件: {filename} ({os.path.getsize(local_path)/1024/1024:.1f}MB)")
            
            # 使用统一上传器上传
            result = await self.uploader.upload_file(
                local_path=local_path,
                remote_path=remote_path,
                file_type="gdrive"
            )
            
            if result.success:
                # 更新数据库状态
                await self.db.update_drive_file_status(
                    drive_file.file_id,
                    'uploaded'
                )
                
                self.stats["files_uploaded"] += 1
                logger.info(f"✅ Google Drive文件上传成功: {remote_path} ({result.duration_seconds:.1f}秒)")
                
                # 发送成功通知
                if self.telegram:
                    await self.telegram.send_message(
                        f"✅ Google Drive文件上传成功\n"
                        f"📁 文件: {filename}\n"
                        f"📊 大小: {result.total_bytes/1024/1024:.1f}MB\n"
                        f"⏱️ 用时: {result.duration_seconds:.1f}秒\n"
                        f"🔗 路径: {remote_path}"
                    )
                
                return True
            else:
                # 上传失败，更新状态
                await self.db.update_drive_file_status(
                    drive_file.file_id,
                    'upload_failed',
                    error_message=result.message
                )
                
                logger.error(f"❌ Google Drive文件上传失败: {result.message}")
                return False
                
        except Exception as e:
            error_msg = f"Google Drive文件上传异常: {e}"
            logger.error(error_msg)
            
            # 更新数据库状态
            await self.db.update_drive_file_status(
                drive_file.file_id,
                'upload_error', 
                error_message=str(e)
            )
            
            return False
    
    async def process_video_gdrive_links(self, video_id: str, description: str) -> ProcessResult:
        """处理视频中的所有Google Drive链接."""
        try:
            # 1. 检测链接
            links = await self.detect_links(description)
            
            if not links:
                return ProcessResult(
                    success=True,
                    message="未检测到Google Drive链接",
                    files_processed=0
                )
            
            errors = []
            files_processed = 0
            files_uploaded = 0
            
            # 2. 为每个链接创建记录并处理
            for link in links:
                try:
                    # 检查是否已存在
                    existing_file = await self.db.get_drive_file_by_id(link.file_id)
                    if existing_file:
                        logger.debug(f"Google Drive文件已存在: {link.file_id}")
                        continue
                    
                    # 创建记录
                    drive_file = await self._create_drive_file_record(video_id, link)
                    files_processed += 1
                    
                    # 下载文件
                    download_success = await self.download_file(drive_file)
                    
                    if download_success:
                        # 重新获取文件信息（包含下载后的路径和大小）
                        updated_file = await self.db.get_drive_file_by_id(link.file_id)
                        if updated_file and self.config.gdrive_upload_to_alist:
                            # 上传文件
                            upload_success = await self.upload_file(updated_file)
                            if upload_success:
                                files_uploaded += 1
                    
                except Exception as e:
                    error_msg = f"处理链接 {link.file_id} 失败: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
            
            return ProcessResult(
                success=len(errors) == 0,
                message=f"处理了 {files_processed} 个文件，上传了 {files_uploaded} 个文件",
                files_processed=files_processed,
                files_uploaded=files_uploaded,
                errors=errors
            )
            
        except Exception as e:
            error_msg = f"处理Google Drive链接失败: {e}"
            logger.error(error_msg)
            return ProcessResult(
                success=False,
                message=error_msg,
                errors=[error_msg]
            )
    
    async def process_pending_downloads(self) -> ProcessResult:
        """处理待下载的Google Drive文件."""
        try:
            pending_files = await self.db.get_pending_drive_files()
            
            if not pending_files:
                return ProcessResult(
                    success=True,
                    message="没有待下载的Google Drive文件",
                    files_processed=0
                )
            
            logger.info(f"开始处理 {len(pending_files)} 个待下载的Google Drive文件")
            
            files_processed = 0
            errors = []
            
            for drive_file in pending_files:
                try:
                    success = await self.download_file(drive_file)
                    if success:
                        files_processed += 1
                except Exception as e:
                    error_msg = f"下载文件 {drive_file.filename} 失败: {e}"
                    errors.append(error_msg)
            
            return ProcessResult(
                success=len(errors) == 0,
                message=f"成功处理 {files_processed} 个文件",
                files_processed=files_processed,
                errors=errors
            )
            
        except Exception as e:
            error_msg = f"处理待下载文件失败: {e}"
            logger.error(error_msg)
            return ProcessResult(
                success=False,
                message=error_msg,
                errors=[error_msg]
            )
    
    async def process_downloaded_files(self) -> ProcessResult:
        """处理已下载但未上传的文件."""
        if not self.config.gdrive_upload_to_alist:
            return ProcessResult(
                success=True,
                message="Google Drive上传已禁用",
                files_processed=0
            )
        
        try:
            # 获取已下载但未上传的文件
            downloaded_files = await self.db.get_drive_files_by_status('downloaded')
            
            if not downloaded_files:
                return ProcessResult(
                    success=True,
                    message="没有待上传的Google Drive文件",
                    files_processed=0
                )
            
            logger.info(f"开始处理 {len(downloaded_files)} 个待上传的Google Drive文件")
            
            files_uploaded = 0
            errors = []
            
            for drive_file in downloaded_files:
                try:
                    success = await self.upload_file(drive_file)
                    if success:
                        files_uploaded += 1
                except Exception as e:
                    error_msg = f"上传文件 {drive_file.filename} 失败: {e}"
                    errors.append(error_msg)
            
            return ProcessResult(
                success=len(errors) == 0,
                message=f"成功上传 {files_uploaded} 个文件",
                files_uploaded=files_uploaded,
                errors=errors
            )
            
        except Exception as e:
            error_msg = f"处理待上传文件失败: {e}"
            logger.error(error_msg)
            return ProcessResult(
                success=False,
                message=error_msg,
                errors=[error_msg]
            )
    
    async def cleanup_failed_files(self, max_age_hours: int = 24) -> int:
        """清理失败的文件记录."""
        try:
            from datetime import datetime, timedelta
            
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            
            # 清理本地文件
            cleanup_count = 0
            failed_files = await self.db.get_drive_files_by_status('failed')
            
            for drive_file in failed_files:
                if drive_file.created_at < cutoff_time and drive_file.file_path:
                    local_path = drive_file.file_path.replace('/app/', './')
                    if os.path.exists(local_path):
                        os.remove(local_path)
                        cleanup_count += 1
                        logger.debug(f"清理失败文件: {local_path}")
            
            return cleanup_count
            
        except Exception as e:
            logger.error(f"清理失败文件时出错: {e}")
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取处理统计信息."""
        try:
            # 获取数据库统计
            db_stats = await self.db.get_drive_files_stats()
            
            # 获取上传器统计
            uploader_stats = self.uploader.get_stats()
            
            return {
                "detection_stats": {
                    "links_detected": self.stats["links_detected"],
                },
                "download_stats": {
                    "files_downloaded": self.stats["files_downloaded"],
                },
                "upload_stats": uploader_stats,
                "database_stats": db_stats,
                "error_stats": {
                    "total_errors": self.stats["errors"],
                }
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}
    
    async def close(self):
        """关闭处理器."""
        if self.downloader:
            await self.downloader.close()