"""统一文件上传器模块."""

import os
import asyncio
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class UploadStatus(Enum):
    """上传状态枚举."""
    PENDING = "pending"
    UPLOADING = "uploading"
    SUCCESS = "success" 
    FAILED = "failed"
    RETRYING = "retrying"


class UploadErrorType(Enum):
    """上传错误类型."""
    NETWORK_TIMEOUT = "network_timeout"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    STORAGE_FULL = "storage_full"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class UploadResult:
    """上传结果."""
    success: bool
    status: UploadStatus
    message: str = ""
    error_type: Optional[UploadErrorType] = None
    bytes_uploaded: int = 0
    total_bytes: int = 0
    duration_seconds: float = 0.0
    remote_path: str = ""


@dataclass
class FileInfo:
    """文件信息."""
    local_path: str
    remote_path: str
    file_size: int
    file_type: str = "unknown"
    metadata: Dict[str, Any] = None


class UploadTimeoutCalculator:
    """智能超时计算器."""
    
    # 基础超时（秒）
    BASE_TIMEOUT = 60
    
    # 每MB所需时间（秒）- 基于不同网络条件
    TIMEOUT_PER_MB = {
        "fast": 1.5,      # 快速网络：1.5秒/MB
        "normal": 3.0,    # 普通网络：3秒/MB  
        "slow": 8.0,      # 慢速网络：8秒/MB
    }
    
    # 最大超时限制
    MAX_TIMEOUT = 1800  # 30分钟
    MIN_TIMEOUT = 60    # 1分钟
    
    def __init__(self, network_quality: str = "normal"):
        """初始化超时计算器."""
        self.network_quality = network_quality
        self.timeout_per_mb = self.TIMEOUT_PER_MB.get(network_quality, 3.0)
    
    def calculate_timeout(self, file_size_bytes: int) -> int:
        """根据文件大小计算合理的超时时间."""
        file_size_mb = file_size_bytes / (1024 * 1024)
        
        # 基础超时 + 文件大小相关的超时
        calculated_timeout = self.BASE_TIMEOUT + (file_size_mb * self.timeout_per_mb)
        
        # 应用上下限制
        timeout = max(self.MIN_TIMEOUT, min(self.MAX_TIMEOUT, calculated_timeout))
        
        logger.debug(f"文件大小: {file_size_mb:.1f}MB, 计算超时: {timeout:.0f}秒")
        return int(timeout)


class UnifiedFileUploader:
    """统一文件上传器."""
    
    def __init__(self, alist_client, database, telegram_notifier=None, max_retries: int = 3):
        """初始化上传器."""
        self.alist = alist_client
        self.db = database
        self.telegram = telegram_notifier
        self.max_retries = max_retries
        self.timeout_calculator = UploadTimeoutCalculator()
        
        # 上传统计
        self.stats = {
            "total_uploads": 0,
            "successful_uploads": 0,
            "failed_uploads": 0,
            "total_bytes_uploaded": 0
        }
    
    def _classify_error(self, error_message: str) -> UploadErrorType:
        """分类错误类型."""
        error_lower = error_message.lower()
        
        if "timeout" in error_lower or "i/o timeout" in error_lower:
            return UploadErrorType.NETWORK_TIMEOUT
        elif "no such file" in error_lower or "not found" in error_lower:
            return UploadErrorType.FILE_NOT_FOUND
        elif "permission denied" in error_lower or "access denied" in error_lower:
            return UploadErrorType.PERMISSION_DENIED
        elif "storage full" in error_lower or "disk full" in error_lower:
            return UploadErrorType.STORAGE_FULL
        else:
            return UploadErrorType.UNKNOWN_ERROR
    
    def _should_retry(self, error_type: UploadErrorType) -> bool:
        """判断是否应该重试."""
        # 网络超时和未知错误可以重试
        return error_type in [UploadErrorType.NETWORK_TIMEOUT, UploadErrorType.UNKNOWN_ERROR]
    
    async def _perform_upload(self, file_info: FileInfo) -> UploadResult:
        """执行实际的上传操作."""
        import time
        start_time = time.time()
        
        try:
            # 验证本地文件
            if not os.path.exists(file_info.local_path):
                return UploadResult(
                    success=False,
                    status=UploadStatus.FAILED,
                    message=f"本地文件不存在: {file_info.local_path}",
                    error_type=UploadErrorType.FILE_NOT_FOUND,
                    total_bytes=file_info.file_size
                )
            
            # 动态计算超时时间
            timeout_seconds = self.timeout_calculator.calculate_timeout(file_info.file_size)
            logger.info(f"开始上传文件: {file_info.local_path} -> {file_info.remote_path} (超时: {timeout_seconds}秒)")
            
            # 提取目录路径
            remote_dir = os.path.dirname(file_info.remote_path)
            
            # 执行上传
            upload_success = await self.alist.upload_file(file_info.local_path, remote_dir)
            
            duration = time.time() - start_time
            
            if upload_success:
                self.stats["successful_uploads"] += 1
                self.stats["total_bytes_uploaded"] += file_info.file_size
                
                return UploadResult(
                    success=True,
                    status=UploadStatus.SUCCESS,
                    message="上传成功",
                    bytes_uploaded=file_info.file_size,
                    total_bytes=file_info.file_size,
                    duration_seconds=duration,
                    remote_path=file_info.remote_path
                )
            else:
                return UploadResult(
                    success=False,
                    status=UploadStatus.FAILED,
                    message="上传失败",
                    error_type=UploadErrorType.UNKNOWN_ERROR,
                    total_bytes=file_info.file_size,
                    duration_seconds=duration
                )
                
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            return UploadResult(
                success=False,
                status=UploadStatus.FAILED,
                message=f"上传超时 ({timeout_seconds}秒)",
                error_type=UploadErrorType.NETWORK_TIMEOUT,
                total_bytes=file_info.file_size,
                duration_seconds=duration
            )
        except Exception as e:
            duration = time.time() - start_time
            error_message = str(e)
            
            return UploadResult(
                success=False,
                status=UploadStatus.FAILED,
                message=f"上传异常: {error_message}",
                error_type=self._classify_error(error_message),
                total_bytes=file_info.file_size,
                duration_seconds=duration
            )
    
    async def upload_with_retry(self, file_info: FileInfo) -> UploadResult:
        """带重试机制的上传."""
        self.stats["total_uploads"] += 1
        
        last_result = None
        
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                # 重试前等待
                wait_time = min(2 ** attempt, 60)  # 指数退避，最大60秒
                logger.info(f"第 {attempt + 1} 次重试上传，等待 {wait_time} 秒...")
                await asyncio.sleep(wait_time)
            
            result = await self._perform_upload(file_info)
            last_result = result
            
            if result.success:
                logger.info(f"上传成功: {file_info.remote_path} ({result.duration_seconds:.1f}秒)")
                return result
            
            # 检查是否应该重试
            if not self._should_retry(result.error_type):
                logger.error(f"不可重试的错误: {result.message}")
                break
            
            if attempt < self.max_retries:
                logger.warning(f"上传失败 (尝试 {attempt + 1}/{self.max_retries + 1}): {result.message}")
        
        # 所有重试都失败了
        self.stats["failed_uploads"] += 1
        logger.error(f"上传最终失败: {file_info.remote_path} - {last_result.message}")
        return last_result
    
    async def cleanup_after_upload(self, local_path: str) -> bool:
        """上传成功后清理本地文件."""
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"已清理本地文件: {local_path}")
                
                # 清理同目录下的信息文件
                info_file = f"{os.path.splitext(local_path)[0]}.info.json"
                if os.path.exists(info_file):
                    os.remove(info_file)
                    logger.debug(f"已清理信息文件: {info_file}")
                
                return True
            return False
        except Exception as e:
            logger.warning(f"清理文件失败: {e}")
            return False
    
    async def upload_file(self, local_path: str, remote_path: str, file_type: str = "unknown") -> UploadResult:
        """统一上传接口."""
        # 获取文件信息
        if not os.path.exists(local_path):
            return UploadResult(
                success=False,
                status=UploadStatus.FAILED,
                message=f"本地文件不存在: {local_path}",
                error_type=UploadErrorType.FILE_NOT_FOUND
            )
        
        file_size = os.path.getsize(local_path)
        
        file_info = FileInfo(
            local_path=local_path,
            remote_path=remote_path,
            file_size=file_size,
            file_type=file_type
        )
        
        # 执行上传
        result = await self.upload_with_retry(file_info)
        
        # 上传成功后清理本地文件
        if result.success:
            await self.cleanup_after_upload(local_path)
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """获取上传统计."""
        return {
            **self.stats,
            "success_rate": (
                self.stats["successful_uploads"] / max(1, self.stats["total_uploads"]) * 100
                if self.stats["total_uploads"] > 0 else 0
            )
        }
    
    def set_network_quality(self, quality: str):
        """设置网络质量以调整超时策略."""
        if quality in self.timeout_calculator.TIMEOUT_PER_MB:
            self.timeout_calculator.network_quality = quality
            self.timeout_calculator.timeout_per_mb = self.timeout_calculator.TIMEOUT_PER_MB[quality]
            logger.info(f"网络质量设置为: {quality}")