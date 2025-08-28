"""Google Drive文件下载模块."""

import os
import asyncio
import logging
import aiohttp
import aiofiles
import subprocess
from typing import Optional, Dict, Any, Callable
from pathlib import Path
import time
from dataclasses import dataclass

from gdrive_detector import DriveLink

logger = logging.getLogger(__name__)


@dataclass
class DownloadProgress:
    """下载进度信息."""
    file_id: str
    filename: str
    downloaded_bytes: int
    total_bytes: int
    speed_bytes_per_sec: float
    eta_seconds: float
    percentage: float


class GoogleDriveDownloader:
    """Google Drive文件下载器."""
    
    def __init__(
        self,
        download_path: str,
        max_concurrent: int = 3,
        max_file_size: int = 1024 * 1024 * 1024,  # 1GB
        chunk_size: int = 8192,
        timeout: int = 300,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None
    ):
        """初始化下载器.
        
        Args:
            download_path: 下载目录
            max_concurrent: 最大并发下载数
            max_file_size: 最大文件大小限制（字节）
            chunk_size: 下载块大小
            timeout: 超时时间（秒）
            progress_callback: 进度回调函数
        """
        self.download_path = Path(download_path)
        self.max_concurrent = max_concurrent
        self.max_file_size = max_file_size
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.progress_callback = progress_callback
        
        # 创建下载目录
        self.download_path.mkdir(parents=True, exist_ok=True)
        
        # 并发控制
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # HTTP会话
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """异步上下文管理器入口."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口."""
        await self.close()
    
    async def start(self):
        """启动下载器."""
        if self.session is None:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=10,
                ttl_dns_cache=300,
                use_dns_cache=True,
            )
            
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
    
    async def close(self):
        """关闭下载器."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def download_file(self, drive_link: DriveLink, custom_filename: Optional[str] = None) -> Dict[str, Any]:
        """下载Google Drive文件.
        
        Args:
            drive_link: Drive链接信息
            custom_filename: 自定义文件名
            
        Returns:
            下载结果字典
        """
        async with self.semaphore:
            return await self._download_file_impl(drive_link, custom_filename)
    
    async def _download_file_impl(self, drive_link: DriveLink, custom_filename: Optional[str]) -> Dict[str, Any]:
        """下载文件实现."""
        result = {
            'success': False,
            'file_id': drive_link.file_id,
            'file_path': None,
            'file_size': 0,
            'error': None,
            'download_url': None
        }
        
        try:
            logger.info(f"开始下载Google Drive文件: {drive_link.file_id}")
            
            # 获取下载URL和文件信息
            download_info = await self._get_download_info(drive_link)
            if not download_info['success']:
                result['error'] = download_info['error']
                return result
            
            download_url = download_info['download_url']
            # 优先使用传递的自定义文件名，避免重复从HTML提取
            filename = custom_filename or download_info['filename'] or f"gdrive_{drive_link.file_id}"
            file_size = download_info['file_size']
            
            # 如果使用了自定义文件名，记录日志
            if custom_filename:
                logger.info(f"使用预设文件名: {custom_filename}")
            elif download_info['filename']:
                logger.info(f"使用HTML提取文件名: {download_info['filename']}")
            else:
                logger.info(f"使用默认文件名格式: {filename}")
            
            result['download_url'] = download_url
            
            # 检查文件大小限制
            if file_size and file_size > self.max_file_size:
                result['error'] = f"文件过大: {file_size} bytes > {self.max_file_size} bytes"
                return result
            
            # 生成本地文件路径
            local_path = self.download_path / filename
            
            # 避免文件名冲突
            counter = 1
            original_path = local_path
            while local_path.exists():
                stem = original_path.stem
                suffix = original_path.suffix
                local_path = original_path.parent / f"{stem}_{counter}{suffix}"
                counter += 1
            
            # 下载文件
            download_result = await self._download_with_progress(
                download_url, local_path, drive_link.file_id, filename, file_size
            )
            
            if download_result['success']:
                # 下载成功后处理文件名
                final_path = await self._process_downloaded_file(local_path, drive_link.file_id, filename)
                
                result['success'] = True
                result['file_path'] = str(final_path)
                result['file_size'] = download_result['file_size']
                logger.info(f"成功下载文件: {final_path}")
            else:
                result['error'] = download_result['error']
                # 清理部分下载的文件
                if local_path.exists():
                    try:
                        local_path.unlink()
                    except Exception as e:
                        logger.warning(f"清理失败的下载文件时出错: {e}")
        
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"下载Google Drive文件失败: {e}")
        
        return result
    
    async def _get_download_info(self, drive_link: DriveLink) -> Dict[str, Any]:
        """获取下载信息."""
        result = {
            'success': False,
            'download_url': None,
            'filename': None,
            'file_size': None,
            'error': None
        }
        
        try:
            # 如果有直接下载链接，先尝试使用
            if drive_link.direct_download_url:
                info = await self._check_direct_download(drive_link.direct_download_url)
                if info['success']:
                    return info
            
            # 尝试多种下载方法
            download_urls = [
                f"https://drive.google.com/uc?export=download&id={drive_link.file_id}",
                f"https://drive.google.com/uc?id={drive_link.file_id}&export=download",
                f"https://drive.usercontent.google.com/download?id={drive_link.file_id}&export=download",
                f"https://drive.google.com/file/d/{drive_link.file_id}/view?usp=sharing",
                drive_link.original_url
            ]
            
            for i, url in enumerate(download_urls, 1):
                try:
                    logger.info(f"尝试下载方法 {i}/{len(download_urls)}: {url[:80]}...")
                    info = await self._check_direct_download(url)
                    if info['success']:
                        logger.info(f"✅ 下载方法 {i} 成功: {url[:80]}...")
                        return info
                    else:
                        logger.warning(f"❌ 下载方法 {i} 失败: {info.get('error', '未知错误')}")
                except Exception as e:
                    logger.warning(f"❌ 下载方法 {i} 异常: {e}")
                    continue
            
            result['error'] = f"所有 {len(download_urls)} 种下载方法都失败了"
            logger.error(f"Google Drive文件 {drive_link.file_id} 所有下载方法均失败")
            
        except Exception as e:
            result['error'] = f"获取下载信息失败: {e}"
        
        return result
    
    async def _check_direct_download(self, url: str) -> Dict[str, Any]:
        """检查直接下载链接."""
        result = {
            'success': False,
            'download_url': url,
            'filename': None,
            'file_size': None,
            'error': None
        }
        
        try:
            async with self.session.head(url, allow_redirects=True) as response:
                if response.status == 200:
                    # 检查Content-Type是否为HTML（表明是确认页面）
                    content_type = response.headers.get('content-type', '').lower()
                    
                    if 'html' in content_type:
                        logger.info(f"HEAD请求返回HTML Content-Type，可能是Google Drive确认页面")
                        # 需要进行GET请求来处理确认页面
                    else:
                        # 获取文件名
                        content_disposition = response.headers.get('content-disposition', '')
                        if 'filename=' in content_disposition:
                            filename = content_disposition.split('filename=')[1].strip('"\'')
                            result['filename'] = filename
                        
                        # 获取文件大小
                        content_length = response.headers.get('content-length')
                        if content_length:
                            result['file_size'] = int(content_length)
                        
                        result['success'] = True
                        return result
            
            # 如果HEAD请求失败或返回HTML Content-Type，尝试GET请求
            async with self.session.get(url) as get_response:
                if get_response.status == 200:
                    # 检查是否是Google Drive的确认页面
                    content = await get_response.text()
                    if 'Google Drive - Virus scan warning' in content or 'confirm=' in content or 'download_warning' in content:
                        logger.info(f"检测到Google Drive病毒扫描警告页面，尝试提取确认链接")
                        
                        # 尝试从HTML提取真实文件名
                        html_filename = self._extract_filename_from_html(content)
                        if html_filename:
                            result['filename'] = html_filename
                        
                        # 尝试提取确认链接
                        confirm_url = await self._extract_confirm_url(content, url)
                        if confirm_url:
                            logger.info(f"成功提取确认下载链接")
                            result['download_url'] = confirm_url
                            result['success'] = True
                        else:
                            result['error'] = "检测到病毒扫描确认页面，但无法提取确认链接"
                            logger.warning("无法从病毒扫描页面提取确认链接")
                    elif 'quota exceeded' in content.lower():
                        result['error'] = "Google Drive配额已超限，无法下载"
                        logger.error("Google Drive下载配额超限")
                    elif 'access denied' in content.lower():
                        result['error'] = "Google Drive访问被拒绝，可能是权限问题"
                        logger.error("Google Drive访问被拒绝")
                    else:
                        result['success'] = True
                else:
                    result['error'] = f"HTTP {get_response.status}: {get_response.reason}"
                            
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def _extract_filename_from_html(self, html_content: str) -> Optional[str]:
        """从HTML内容中提取真实文件名."""
        import re
        
        # 查找多种可能的文件名模式
        patterns = [
            # Google Drive标准格式: <a href="/open?id=...">filename.ext</a>
            r'<a[^>]+href="/open\?id=[^"]*"[^>]*>([^<]+)</a>',
            # 其他可能的文件名显示格式
            r'<span[^>]+class="[^"]*name[^"]*"[^>]*>([^<]+)</span>',
            # 直接在页面标题中的文件名
            r'<title>([^<]*\.[\w]+)[^<]*</title>',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            if matches:
                filename = matches[0].strip()
                # 验证文件名是否有效（包含扩展名）
                if '.' in filename and not filename.startswith('Google Drive'):
                    # 清理文件名中的特殊字符
                    filename = self._sanitize_filename(filename)
                    logger.info(f"从HTML提取到文件名: {filename}")
                    return filename
        
        logger.debug("未从HTML中找到有效文件名")
        return None
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除不安全字符."""
        import re
        # 移除或替换不安全的字符
        unsafe_chars = r'[<>:"/\\|?*]'
        filename = re.sub(unsafe_chars, '_', filename)
        # 移除多余的空格和点
        filename = re.sub(r'\s+', ' ', filename).strip()
        filename = re.sub(r'\.+', '.', filename)
        return filename

    def _detect_file_type(self, file_path: str) -> Optional[str]:
        """检测文件类型并返回合适的扩展名."""
        try:
            # 使用file命令检测文件类型
            result = subprocess.run(
                ['file', '--mime-type', '-b', file_path], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            if result.returncode == 0:
                mime_type = result.stdout.strip()
                
                # MIME类型到扩展名的映射
                mime_to_ext = {
                    # 视频格式
                    'video/mp4': '.mp4',
                    'video/x-msvideo': '.avi',
                    'video/quicktime': '.mov',
                    'video/x-matroska': '.mkv',
                    'video/webm': '.webm',
                    'video/x-flv': '.flv',
                    
                    # 音频格式
                    'audio/mpeg': '.mp3',
                    'audio/mp4': '.m4a',
                    'audio/wav': '.wav',
                    'audio/x-flac': '.flac',
                    'audio/ogg': '.ogg',
                    
                    # 图片格式
                    'image/jpeg': '.jpg',
                    'image/png': '.png',
                    'image/gif': '.gif',
                    'image/webp': '.webp',
                    'image/svg+xml': '.svg',
                    
                    # 文档格式
                    'application/pdf': '.pdf',
                    'application/msword': '.doc',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
                    'application/vnd.ms-excel': '.xls',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
                    'application/vnd.ms-powerpoint': '.ppt',
                    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
                    
                    # 压缩格式
                    'application/zip': '.zip',
                    'application/x-rar-compressed': '.rar',
                    'application/x-7z-compressed': '.7z',
                    'application/gzip': '.gz',
                    'application/x-tar': '.tar',
                    
                    # 文本格式
                    'text/plain': '.txt',
                    'text/csv': '.csv',
                    'application/json': '.json',
                    'text/xml': '.xml',
                    'text/html': '.html',
                }
                
                extension = mime_to_ext.get(mime_type)
                if extension:
                    logger.info(f"检测到文件类型: {mime_type} -> {extension}")
                    return extension
                else:
                    logger.debug(f"未知MIME类型: {mime_type}")
                    
        except subprocess.TimeoutExpired:
            logger.warning(f"文件类型检测超时: {file_path}")
        except Exception as e:
            logger.warning(f"文件类型检测失败: {e}")
            
        return None

    def _generate_smart_filename(self, file_id: str, detected_extension: Optional[str] = None) -> str:
        """生成智能文件名."""
        # 使用文件ID的前8位作为简短标识
        short_id = file_id[:8]
        
        if detected_extension:
            return f"gdrive_{short_id}{detected_extension}"
        else:
            return f"gdrive_{short_id}"

    async def _process_downloaded_file(self, local_path: Path, file_id: str, original_filename: str) -> Path:
        """处理下载完成的文件，包括重命名和类型检测."""
        try:
            # 检查原始文件名是否已经有扩展名
            if '.' in original_filename and not original_filename.startswith('gdrive_'):
                # 如果原始文件名有扩展名且不是默认格式，直接返回
                logger.info(f"文件已有有效文件名: {original_filename}")
                return local_path
            
            # 如果是默认的gdrive_格式，尝试改进
            if original_filename.startswith('gdrive_') and '.' not in original_filename:
                logger.info(f"检测到默认文件名格式，尝试改进: {original_filename}")
                
                # 检测文件类型
                detected_extension = self._detect_file_type(str(local_path))
                
                if detected_extension:
                    # 生成新的文件名
                    new_filename = self._generate_smart_filename(file_id, detected_extension)
                    new_path = local_path.parent / new_filename
                    
                    # 避免文件名冲突
                    counter = 1
                    original_new_path = new_path
                    while new_path.exists() and new_path != local_path:
                        stem = original_new_path.stem
                        suffix = original_new_path.suffix
                        new_path = original_new_path.parent / f"{stem}_{counter}{suffix}"
                        counter += 1
                    
                    # 重命名文件
                    if new_path != local_path:
                        local_path.rename(new_path)
                        logger.info(f"文件已重命名: {local_path.name} -> {new_path.name}")
                        return new_path
                    
        except Exception as e:
            logger.warning(f"处理下载文件时出错，使用原文件名: {e}")
        
        return local_path

    async def _extract_confirm_url(self, html_content: str, original_url: str) -> Optional[str]:
        """从HTML内容中提取确认下载链接."""
        import re
        
        try:
            # 方法1: 解析表单参数构建下载链接
            action_match = re.search(r'action="([^"]*)"', html_content)
            if action_match:
                action_url = action_match.group(1)
                logger.info(f"找到表单action: {action_url}")
                
                # 提取所有input参数
                params = {}
                # 使用更简单的方式分别提取name和value
                name_matches = re.findall(r'<input[^>]+name="([^"]+)"[^>]*>', html_content)
                value_matches = re.findall(r'<input[^>]+value="([^"]*)"[^>]*>', html_content)
                
                # 同时查找name和value在同一个input标签中
                input_tags = re.findall(r'<input[^>]*(?:name="([^"]*)"[^>]*value="([^"]*)"|value="([^"]*)"[^>]*name="([^"]*)")[^>]*>', html_content)
                
                for match in input_tags:
                    if match[0] and match[1]:  # name first, then value
                        name, value = match[0], match[1]
                    elif match[2] and match[3]:  # value first, then name  
                        value, name = match[2], match[3]
                    else:
                        continue
                        
                    if name in ['id', 'export', 'confirm', 'uuid']:
                        params[name] = value
                        logger.info(f"提取参数: {name}={value}")
                
                # 构建确认下载URL
                if 'id' in params:
                    confirm_url = f"{action_url}?id={params['id']}&export={params.get('export', 'download')}"
                    if 'confirm' in params:
                        confirm_url += f"&confirm={params['confirm']}"
                    if 'uuid' in params:
                        confirm_url += f"&uuid={params['uuid']}"
                    
                    logger.info(f"构建确认下载链接: {confirm_url}")
                    return confirm_url
                else:
                    logger.warning(f"未找到id参数，找到的参数: {params}")
                    
            else:
                logger.warning("未找到表单action")
            
            # 方法2: 查找现有的确认链接模式
            patterns = [
                # 标准确认下载链接
                r'href="(/uc\?export=download[^"]+)"',
                r"href='(/uc\?export=download[^']+)'",
                r'action="([^"]*uc\?export=download[^"]*)"',
                # 新版Google Drive确认链接
                r'href="([^"]*download\?id=[^"]*&amp;confirm=[^"]*)"',
                r'href="([^"]*download\?id=[^"]*&confirm=[^"]*)"',
                # 通用确认参数
                r'confirm=([a-zA-Z0-9_-]+)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, html_content)
                if matches:
                    confirm_path = matches[0]
                    logger.debug(f"找到确认链接模式: {pattern} -> {confirm_path}")
                    
                    # 处理不同类型的匹配结果
                    if confirm_path.startswith('/'):
                        return f"https://drive.google.com{confirm_path}"
                    elif confirm_path.startswith('http'):
                        # 清理HTML实体编码
                        return confirm_path.replace('&amp;', '&')
                    elif len(confirm_path) > 10:  # 确认码
                        # 从原始URL提取文件ID
                        from urllib.parse import urlparse, parse_qs
                        try:
                            parsed = urlparse(original_url)
                            file_id = None
                            if '/file/d/' in original_url:
                                file_id = original_url.split('/file/d/')[1].split('/')[0]
                            elif 'id=' in original_url:
                                query_params = parse_qs(parsed.query)
                                file_id = query_params.get('id', [None])[0]
                            
                            if file_id:
                                return f"https://drive.google.com/uc?export=download&id={file_id}&confirm={confirm_path}"
                        except Exception as e:
                            logger.warning(f"构建确认URL失败: {e}")
                            continue
            
        except Exception as e:
            logger.error(f"解析确认链接时出错: {e}")
        
        logger.warning("未找到有效的确认下载链接")
        return None
    
    async def _download_with_progress(
        self, 
        url: str, 
        local_path: Path, 
        file_id: str, 
        filename: str, 
        expected_size: Optional[int]
    ) -> Dict[str, Any]:
        """带进度的文件下载."""
        result = {
            'success': False,
            'file_size': 0,
            'error': None
        }
        
        start_time = time.time()
        downloaded_bytes = 0
        
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    result['error'] = f"HTTP {response.status}: {response.reason}"
                    return result
                
                # 获取实际文件大小
                content_length = response.headers.get('content-length')
                total_bytes = int(content_length) if content_length else expected_size or 0
                
                # 打开本地文件进行写入
                async with aiofiles.open(local_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(self.chunk_size):
                        await f.write(chunk)
                        downloaded_bytes += len(chunk)
                        
                        # 计算进度并调用回调
                        if self.progress_callback and total_bytes > 0:
                            elapsed_time = time.time() - start_time
                            if elapsed_time > 0:
                                speed = downloaded_bytes / elapsed_time
                                eta = (total_bytes - downloaded_bytes) / speed if speed > 0 else 0
                                percentage = (downloaded_bytes / total_bytes) * 100
                                
                                progress = DownloadProgress(
                                    file_id=file_id,
                                    filename=filename,
                                    downloaded_bytes=downloaded_bytes,
                                    total_bytes=total_bytes,
                                    speed_bytes_per_sec=speed,
                                    eta_seconds=eta,
                                    percentage=percentage
                                )
                                
                                try:
                                    self.progress_callback(progress)
                                except Exception as e:
                                    logger.warning(f"进度回调函数出错: {e}")
                
                result['success'] = True
                result['file_size'] = downloaded_bytes
                
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    async def download_multiple(self, drive_links: list[DriveLink]) -> list[Dict[str, Any]]:
        """批量下载多个文件."""
        if not drive_links:
            return []
        
        logger.info(f"开始批量下载 {len(drive_links)} 个Google Drive文件")
        
        # 创建下载任务
        tasks = []
        for drive_link in drive_links:
            task = asyncio.create_task(self.download_file(drive_link))
            tasks.append(task)
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append({
                    'success': False,
                    'file_id': drive_links[i].file_id,
                    'file_path': None,
                    'file_size': 0,
                    'error': str(result),
                    'download_url': None
                })
            else:
                final_results.append(result)
        
        successful = sum(1 for r in final_results if r['success'])
        logger.info(f"批量下载完成: {successful}/{len(drive_links)} 成功")
        
        return final_results


def format_bytes(bytes_size: float) -> str:
    """格式化字节大小."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


def format_time(seconds: float) -> str:
    """格式化时间."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}m {seconds%60:.0f}s"
    else:
        return f"{seconds/3600:.0f}h {(seconds%3600)/60:.0f}m"