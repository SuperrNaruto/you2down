"""Instagram客户端模块 - 用于获取收藏的视频信息."""

import json
import asyncio
import aiohttp
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import logging
from pathlib import Path
from functools import partial

logger = logging.getLogger(__name__)


class InstagramMedia:
    """Instagram媒体信息类."""
    
    def __init__(self, data: Dict[str, Any]):
        self.id = data.get('id', '')
        self.shortcode = data.get('shortcode', '')
        self.url = f"https://www.instagram.com/p/{self.shortcode}/"
        self.media_type = data.get('media_type', 1)  # 1=photo, 2=video
        self.caption = data.get('caption', {}).get('text', '') if data.get('caption') else ''
        self.timestamp = datetime.fromtimestamp(data.get('taken_at', 0))
        self.username = data.get('user', {}).get('username', '')
        self.is_video = self.media_type == 2
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式."""
        return {
            'id': self.id,
            'shortcode': self.shortcode,
            'url': self.url,
            'media_type': self.media_type,
            'caption': self.caption,
            'timestamp': self.timestamp.isoformat(),
            'username': self.username,
            'is_video': self.is_video
        }


class InstagramClient:
    """Instagram客户端 - 使用instaloader获取收藏内容."""
    
    def __init__(self, username: str = "", password: str = "", session_file: str = "", 
                 max_retries: int = 5, retry_delay: int = 60, use_proxy: bool = False,
                 proxy_host: str = "", proxy_port: int = 0, custom_user_agent: str = ""):
        """初始化Instagram客户端."""
        self.username = username
        self.password = password
        self.session_file = session_file
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.use_proxy = use_proxy
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.custom_user_agent = custom_user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.session = None
        self._loader = None
        self._session_valid = False
        self._last_session_check = datetime.now() - timedelta(hours=2)
        
    def _is_session_expired(self) -> bool:
        """检查会话是否过期."""
        # 每1小时检查一次会话状态
        return datetime.now() - self._last_session_check > timedelta(hours=1)
    
    def _validate_session_file(self) -> bool:
        """验证会话文件是否有效."""
        if not self.session_file or not Path(self.session_file).exists():
            return False
        
        try:
            # 检查文件修改时间，如果超过24小时认为可能过期
            session_file_path = Path(self.session_file)
            file_age = datetime.now() - datetime.fromtimestamp(session_file_path.stat().st_mtime)
            if file_age > timedelta(hours=24):
                logger.warning(f"会话文件可能已过期，文件年龄: {file_age}")
                return False
            
            # 检查文件大小，如果太小可能是无效的
            if session_file_path.stat().st_size < 100:
                logger.warning("会话文件太小，可能无效")
                return False
            
            return True
        except Exception as e:
            logger.warning(f"验证会话文件时出错: {e}")
            return False
    
    async def _attempt_login_with_retry(self) -> bool:
        """带重试的登录尝试."""
        for attempt in range(self.max_retries):
            try:
                # 在线程池中尝试登录
                login_func = partial(self._login_sync)
                success = await asyncio.get_event_loop().run_in_executor(
                    self.executor, login_func
                )
                
                if success:
                    self._session_valid = True
                    self._last_session_check = datetime.now()
                    return True
                
            except Exception as e:
                logger.warning(f"登录尝试 {attempt + 1}/{self.max_retries} 失败: {e}")
                
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)  # 指数退避
                    logger.info(f"等待 {delay} 秒后重试...")
                    await asyncio.sleep(delay)
        
        return False
    
    def _login_sync(self) -> bool:
        """同步登录方法."""
        try:
            if not self.username or not self.password:
                return False
            
            self._loader.login(self.username, self.password)
            
            # 保存会话
            if self.session_file:
                session_dir = Path(self.session_file).parent
                session_dir.mkdir(parents=True, exist_ok=True)
                self._loader.save_session_to_file(self.session_file)
                logger.info(f"会话已保存到: {self.session_file}")
                
            logger.info(f"Instagram登录成功: {self.username}")
            return True
            
        except Exception as e:
            logger.error(f"登录失败: {e}")
            return False
        
    async def init(self) -> None:
        """初始化Instagram loader."""
        try:
            # 由于instaloader是同步库，我们需要在线程池中运行
            import concurrent.futures
            
            # 创建线程池executor用于运行同步代码
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            
            # 在线程池中初始化instaloader
            init_func = partial(self._init_loader)
            await asyncio.get_event_loop().run_in_executor(self.executor, init_func)
            
            logger.info("Instagram客户端初始化完成")
            
        except ImportError:
            logger.error("请安装instaloader库: pip install instaloader")
            raise
        except Exception as e:
            logger.error(f"Instagram客户端初始化失败: {e}")
            raise
    
    def _init_loader(self) -> None:
        """在线程池中初始化instaloader."""
        try:
            import instaloader
            
            # 创建instaloader实例，配置用户代理
            self._loader = instaloader.Instaloader(
                user_agent=self.custom_user_agent,
                sleep=True,  # 启用请求间隔
                compress_json=True  # 压缩会话文件
            )
            
            # 配置代理（如果启用）
            if self.use_proxy and self.proxy_host and self.proxy_port:
                try:
                    import requests
                    proxies = {
                        'http': f'http://{self.proxy_host}:{self.proxy_port}',
                        'https': f'http://{self.proxy_host}:{self.proxy_port}'
                    }
                    # 注意：instaloader不直接支持代理，需要通过环境变量或其他方式设置
                    logger.info(f"尝试使用代理: {self.proxy_host}:{self.proxy_port}")
                except Exception as e:
                    logger.warning(f"配置代理失败: {e}")
            
            # 尝试从会话文件加载
            if self._validate_session_file():
                try:
                    self._loader.load_session_from_file(self.username, self.session_file)
                    logger.info("从会话文件加载Instagram登录状态")
                    
                    # 简单测试会话是否有效
                    try:
                        # 尝试获取用户信息验证会话
                        profile = instaloader.Profile.from_username(self._loader.context, self.username)
                        self._session_valid = True
                        self._last_session_check = datetime.now()
                        logger.info("会话验证成功")
                        return
                    except Exception as e:
                        logger.warning(f"会话验证失败: {e}，将尝试重新登录")
                        
                except Exception as e:
                    logger.warning(f"加载会话文件失败: {e}")
            
            # 如果会话无效或不存在，尝试登录
            if self.username and self.password:
                success = self._login_sync()
                if not success:
                    raise Exception("登录失败")
            else:
                logger.warning("未配置Instagram登录信息，将使用匿名模式（功能有限）")
                
        except Exception as e:
            logger.error(f"初始化instaloader失败: {e}")
            raise
    
    async def get_saved_media(self, limit: int = 50) -> List[InstagramMedia]:
        """获取用户收藏的媒体内容（带重试机制）."""
        if not self._loader:
            raise RuntimeError("Instagram客户端未初始化")
            
        if not self.username:
            raise RuntimeError("获取收藏内容需要登录")
        
        # 如果会话可能过期，先验证
        if self._is_session_expired() or not self._session_valid:
            await self._refresh_session_if_needed()
        
        # 带重试的执行
        for attempt in range(self.max_retries):
            try:
                # 在线程池中执行
                func = partial(self._get_saved_media_sync, limit)
                result = await asyncio.get_event_loop().run_in_executor(
                    self.executor, func
                )
                return result
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"获取Instagram收藏失败，尝试 {attempt + 1}/{self.max_retries}: {error_msg}")
                
                # 检查是否是401错误或会话相关错误
                if "401" in error_msg or "unauthorized" in error_msg.lower() or "session" in error_msg.lower():
                    logger.info("检测到认证错误，尝试刷新会话...")
                    try:
                        await self._refresh_session_if_needed(force=True)
                    except Exception as refresh_error:
                        logger.error(f"刷新会话失败: {refresh_error}")
                
                # 如果是最后一次尝试，抛出异常
                if attempt == self.max_retries - 1:
                    logger.error(f"所有重试均失败，获取Instagram收藏失败: {error_msg}")
                    raise
                
                # 等待后重试，使用指数退避
                delay = self.retry_delay * (2 ** attempt)
                logger.info(f"等待 {delay} 秒后重试...")
                await asyncio.sleep(delay)
    
    async def _refresh_session_if_needed(self, force: bool = False) -> None:
        """刷新会话（如果需要）."""
        if not force and self._session_valid and not self._is_session_expired():
            return
        
        logger.info("尝试刷新Instagram会话...")
        
        # 在线程池中重新初始化
        try:
            init_func = partial(self._init_loader)
            await asyncio.get_event_loop().run_in_executor(self.executor, init_func)
            logger.info("Instagram会话刷新成功")
        except Exception as e:
            logger.error(f"刷新Instagram会话失败: {e}")
            self._session_valid = False
            raise
    
    def _get_saved_media_sync(self, limit: int) -> List[InstagramMedia]:
        """同步方法获取收藏内容."""
        import instaloader
        
        try:
            # 获取当前用户的profile
            profile = instaloader.Profile.from_username(
                self._loader.context, self.username
            )
            
            saved_posts = []
            count = 0
            
            # 获取收藏的帖子
            for post in profile.get_saved_posts():
                if count >= limit:
                    break
                    
                # 只处理视频
                if post.is_video:
                    # 转换为InstagramMedia格式
                    media_data = {
                        'id': post.mediaid,
                        'shortcode': post.shortcode,
                        'media_type': 2,  # video
                        'caption': {'text': post.caption} if post.caption else None,
                        'taken_at': post.date_utc.timestamp(),
                        'user': {'username': post.owner_username}
                    }
                    
                    saved_posts.append(InstagramMedia(media_data))
                    count += 1
            
            logger.info(f"获取到 {len(saved_posts)} 个收藏视频")
            return saved_posts
            
        except Exception as e:
            logger.error(f"获取收藏内容失败: {e}")
            raise
    
    async def get_media_info(self, shortcode: str) -> Optional[InstagramMedia]:
        """根据shortcode获取媒体信息."""
        if not self._loader:
            raise RuntimeError("Instagram客户端未初始化")
        
        try:
            func = partial(self._get_media_info_sync, shortcode)
            result = await asyncio.get_event_loop().run_in_executor(
                self.executor, func
            )
            return result
            
        except Exception as e:
            logger.error(f"获取媒体信息失败 {shortcode}: {e}")
            return None
    
    def _get_media_info_sync(self, shortcode: str) -> Optional[InstagramMedia]:
        """同步获取媒体信息."""
        import instaloader
        
        try:
            post = instaloader.Post.from_shortcode(
                self._loader.context, shortcode
            )
            
            if not post.is_video:
                return None
            
            media_data = {
                'id': post.mediaid,
                'shortcode': post.shortcode,
                'media_type': 2,  # video
                'caption': {'text': post.caption} if post.caption else None,
                'taken_at': post.date_utc.timestamp(),
                'user': {'username': post.owner_username}
            }
            
            return InstagramMedia(media_data)
            
        except Exception as e:
            logger.error(f"获取媒体信息失败: {e}")
            return None
    
    async def close(self) -> None:
        """关闭客户端."""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)
        logger.info("Instagram客户端已关闭")


# 使用yt-dlp作为备选方案的简化客户端
class InstagramYtDlpClient:
    """使用yt-dlp的简化Instagram客户端."""
    
    def __init__(self):
        """初始化客户端."""
        self.session = None
    
    async def init(self) -> None:
        """初始化客户端."""
        logger.info("Instagram yt-dlp客户端初始化完成")
    
    async def download_by_urls(self, urls: List[str], output_path: str) -> List[str]:
        """根据URL列表下载视频."""
        import yt_dlp
        
        downloaded_files = []
        
        ydl_opts = {
            'outtmpl': f'{output_path}/%(uploader)s_%(id)s.%(ext)s',
            'format': 'best[ext=mp4]',
            'writeinfojson': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                for url in urls:
                    try:
                        info = ydl.extract_info(url, download=True)
                        if info:
                            filename = ydl.prepare_filename(info)
                            downloaded_files.append(filename)
                            logger.info(f"下载完成: {filename}")
                    except Exception as e:
                        logger.error(f"下载失败 {url}: {e}")
                        
        except Exception as e:
            logger.error(f"批量下载失败: {e}")
        
        return downloaded_files
    
    async def close(self) -> None:
        """关闭客户端."""
        logger.info("Instagram yt-dlp客户端已关闭")