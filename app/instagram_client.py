"""Instagram客户端模块 - 简化版，专注核心功能."""

import json
import asyncio
import aiohttp
import time
import random
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import logging
from pathlib import Path

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
    """Instagram客户端 - 简化版本，专注核心功能."""
    
    def __init__(self, username: str = "", password: str = "", session_file: str = "", 
                 cookie_file: str = "", max_retries: int = 5, retry_delay: int = 60, 
                 custom_user_agent: str = "", request_delay: float = 2.0, rate_limit_window: int = 300):
        """初始化Instagram客户端."""
        self.username = username
        self.password = password
        self.session_file = session_file
        self.cookie_file = cookie_file
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.custom_user_agent = custom_user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.request_delay = request_delay
        self.rate_limit_window = rate_limit_window
        
        self.session = None
        self._loader = None
        self._session_valid = False
        self._last_session_check = datetime.now() - timedelta(hours=2)
        self._last_request_time = datetime.now() - timedelta(minutes=5)
        self._request_count = 0
        self._rate_limit_start = datetime.now()
        
        # 简化的User-Agent库
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        
    def __del__(self):
        """清理资源."""
        if hasattr(self, 'session') and self.session and not self.session.closed:
            asyncio.create_task(self._close_session())
            
    async def _close_session(self):
        """异步关闭session."""
        try:
            if self.session and not self.session.closed:
                await self.session.close()
        except Exception as e:
            logger.debug(f"关闭session时出错: {e}")
            
    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent."""
        return random.choice(self.user_agents)
        
    def _get_browser_headers(self, user_agent: str = None) -> Dict[str, str]:
        """获取浏览器标准请求头."""
        ua = user_agent or self.custom_user_agent
        return {
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        
    def _validate_session_file(self) -> bool:
        """验证会话文件是否有效."""
        if not self.session_file or not os.path.exists(self.session_file):
            return False
            
        try:
            with open(self.session_file, 'r') as f:
                session_data = json.load(f)
                return bool(session_data)
        except Exception as e:
            logger.warning(f"会话文件验证失败: {e}")
            return False
            
    def _should_refresh_session(self) -> bool:
        """判断是否需要刷新会话."""
        # 每2小时检查一次会话有效性
        time_since_check = datetime.now() - self._last_session_check
        if time_since_check.total_seconds() > 7200:
            return True
            
        # 如果会话标记为无效，则需要刷新
        if not self._session_valid:
            return True
            
        return False
    
    def _load_cookies_from_file(self) -> bool:
        """从cookie文件加载cookies."""
        if not self.cookie_file or not os.path.exists(self.cookie_file):
            return False
            
        try:
            with open(self.cookie_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
            # 支持多种cookie格式
            cookies = self._parse_cookies(content)
            if not cookies:
                logger.warning("无法解析cookie文件")
                return False
                
            # 将cookies设置到instaloader
            if self._loader and hasattr(self._loader, 'context'):
                self._loader.context._session.cookies.clear()
                for cookie in cookies:
                    self._loader.context._session.cookies.set(
                        cookie['name'], 
                        cookie['value'], 
                        domain=cookie.get('domain', '.instagram.com'),
                        path=cookie.get('path', '/')
                    )
                    
            logger.info(f"已从cookie文件加载 {len(cookies)} 个cookies")
            return True
            
        except Exception as e:
            logger.error(f"加载cookie文件失败: {e}")
            return False
            
    def _parse_cookies(self, content: str) -> List[Dict[str, Any]]:
        """解析cookie内容，支持多种格式."""
        cookies = []
        
        try:
            # 格式1: JSON数组格式 (Chrome插件导出)
            if content.strip().startswith('['):
                cookie_data = json.loads(content)
                for cookie in cookie_data:
                    if isinstance(cookie, dict) and 'name' in cookie and 'value' in cookie:
                        # 过滤Instagram相关的cookies
                        if any(domain in cookie.get('domain', '') for domain in ['.instagram.com', 'instagram.com']):
                            cookies.append(cookie)
                return cookies
                
            # 格式2: Netscape格式
            elif '# Netscape HTTP Cookie File' in content or '\t' in content:
                lines = content.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split('\t')
                        if len(parts) >= 7:
                            cookies.append({
                                'name': parts[5],
                                'value': parts[6],
                                'domain': parts[0],
                                'path': parts[2],
                                'secure': parts[3].lower() == 'true',
                                'httpOnly': parts[1].lower() == 'true'
                            })
                return cookies
                
            # 格式3: 简单的键值对格式 (name=value; name2=value2)
            else:
                for item in content.split(';'):
                    item = item.strip()
                    if '=' in item:
                        name, value = item.split('=', 1)
                        cookies.append({
                            'name': name.strip(),
                            'value': value.strip(),
                            'domain': '.instagram.com',
                            'path': '/'
                        })
                return cookies
                
        except Exception as e:
            logger.error(f"解析cookie内容失败: {e}")
            
        return []
        
    def _validate_cookies(self) -> bool:
        """验证cookies是否有效."""
        if not self._loader or not hasattr(self._loader, 'context'):
            return False
            
        try:
            # 检查关键的Instagram cookies
            required_cookies = ['sessionid', 'csrftoken']
            cookies = self._loader.context._session.cookies
            
            for cookie_name in required_cookies:
                if not any(cookie.name == cookie_name for cookie in cookies):
                    logger.warning(f"缺少关键cookie: {cookie_name}")
                    return False
                    
            # 尝试简单的API调用来验证cookies
            # 这里可以添加更复杂的验证逻辑
            logger.info("Cookies验证成功")
            return True
            
        except Exception as e:
            logger.error(f"验证cookies失败: {e}")
            return False
        
    async def __init_loader(self) -> bool:
        """初始化instaloader客户端."""
        try:
            import instaloader
        except ImportError:
            logger.error("请安装instaloader库: pip install instaloader")
            return False
            
        try:
            # 使用随机User-Agent
            current_ua = self._get_random_user_agent()
            
            # 简化的instaloader配置
            self._loader = instaloader.Instaloader(
                user_agent=current_ua,
                sleep=True,  # 启用请求间隔
                compress_json=True,  # 压缩会话文件
                max_connection_attempts=3,
                request_timeout=30
            )
            
            # 设置基本请求延迟
            if hasattr(self._loader, 'context'):
                self._loader.context.sleep = random.uniform(2.0, 4.0)
            
            # 认证优先级：cookie文件 > 会话文件 > 用户名密码
            auth_success = False
            
            # 1. 尝试从cookie文件加载
            if self.cookie_file and os.path.exists(self.cookie_file):
                try:
                    if self._load_cookies_from_file():
                        if self._validate_cookies():
                            logger.info("已成功加载Instagram cookie文件")
                            self._session_valid = True
                            auth_success = True
                        else:
                            logger.warning("Cookie文件无效，尝试其他认证方式")
                    else:
                        logger.warning("加载cookie文件失败，尝试其他认证方式")
                except Exception as e:
                    logger.warning(f"处理cookie文件失败: {e}")
            
            # 2. 尝试从会话文件加载
            if not auth_success and self._validate_session_file():
                try:
                    self._loader.load_session_from_file(self.username, self.session_file)
                    logger.info("已加载Instagram会话文件")
                    self._session_valid = True
                    auth_success = True
                except Exception as e:
                    logger.warning(f"加载会话文件失败: {e}")
                    self._session_valid = False
            
            # 3. 如果前面都失败且有用户名密码，尝试登录
            if not auth_success and self.username and self.password:
                try:
                    logger.info("正在登录Instagram...")
                    self._loader.login(self.username, self.password)
                    
                    # 保存会话
                    if self.session_file:
                        Path(self.session_file).parent.mkdir(parents=True, exist_ok=True)
                        self._loader.save_session_to_file(self.session_file)
                        logger.info(f"已保存Instagram会话到: {self.session_file}")
                    
                    self._session_valid = True
                    auth_success = True
                    logger.info("Instagram登录成功")
                except Exception as e:
                    logger.error(f"Instagram登录失败: {e}")
                    return False
            
            # 检查最终认证状态
            if not auth_success:
                logger.error("所有认证方式都失败了，请检查cookie文件、会话文件或用户名密码配置")
                return False
            
            self._last_session_check = datetime.now()
            return True
            
        except Exception as e:
            logger.error(f"初始化Instagram客户端失败: {e}")
            return False
            
    async def initialize(self) -> bool:
        """初始化客户端."""
        return await self.__init_loader()
        
    async def refresh_session(self) -> bool:
        """刷新会话."""
        logger.info("正在刷新Instagram会话...")
        self._session_valid = False
        
        # 如果有cookie文件，优先尝试重新加载cookie
        if self.cookie_file and os.path.exists(self.cookie_file):
            logger.info("尝试重新加载cookie文件...")
            
        return await self.__init_loader()
        
    def _is_cookie_expired(self) -> bool:
        """检查cookie是否过期."""
        if not self._loader or not hasattr(self._loader, 'context'):
            return True
            
        try:
            cookies = self._loader.context._session.cookies
            sessionid_cookie = None
            
            for cookie in cookies:
                if cookie.name == 'sessionid':
                    sessionid_cookie = cookie
                    break
                    
            if not sessionid_cookie:
                return True
                
            # 检查cookie是否有过期时间
            if hasattr(sessionid_cookie, 'expires') and sessionid_cookie.expires:
                import datetime
                now = datetime.datetime.now().timestamp()
                return now >= sessionid_cookie.expires
                
            # 如果没有过期时间，检查cookie的年龄
            # Instagram的sessionid cookie通常有效期为90天
            cookie_age = (datetime.now() - self._last_session_check).days
            return cookie_age > 85  # 85天后认为可能需要刷新
            
        except Exception as e:
            logger.warning(f"检查cookie过期状态失败: {e}")
            return True
        
    async def get_liked_posts(self, limit: int = 50) -> List[InstagramMedia]:
        """获取点赞过的帖子 - 通过feed + 过滤器实现."""
        if not self._loader:
            if not await self.initialize():
                return []
                
        # 检查是否需要刷新会话
        if self._should_refresh_session():
            if not await self.refresh_session():
                return []
                
        try:
            import instaloader
            
            # 应用速率限制
            await self._apply_rate_limiting()
            
            liked_posts = []
            
            # 获取用户的feed (关注的人的帖子)
            logger.info("正在获取feed中点赞过的帖子...")
            
            # 使用 get_feed_posts 方法获取feed
            feed_posts = self._loader.get_feed_posts()
            
            count = 0
            for post in feed_posts:
                if len(liked_posts) >= limit:
                    break
                    
                count += 1
                # 只处理点赞过的视频
                if hasattr(post, 'viewer_has_liked') and post.viewer_has_liked and post.is_video:
                    media_data = {
                        'id': post.mediaid,
                        'shortcode': post.shortcode,
                        'media_type': 2,  # video
                        'caption': {'text': post.caption} if post.caption else None,
                        'taken_at': post.date_utc.timestamp(),
                        'user': {'username': post.owner_username}
                    }
                    liked_posts.append(InstagramMedia(media_data))
                    logger.info(f"找到点赞视频: {post.shortcode} by {post.owner_username}")
                
                # 添加请求间隔
                await asyncio.sleep(random.uniform(3.0, 5.0))
                
                # 限制扫描范围，避免无限循环
                if count >= limit * 10:  # 最多扫描 limit*10 个帖子
                    break
                
            logger.info(f"扫描了 {count} 个帖子，获取到 {len(liked_posts)} 个点赞视频")
            return liked_posts
            
        except Exception as e:
            logger.error(f"获取点赞帖子失败: {e}")
            # 如果是认证错误，尝试刷新会话
            if "401" in str(e) or "login" in str(e).lower():
                if await self.refresh_session():
                    return await self.get_liked_posts(limit)
            return []
    
    async def get_saved_media(self, limit: int = 50) -> List[InstagramMedia]:
        """兼容方法：获取点赞过的媒体（替代原来的收藏功能）."""
        logger.info("正在获取点赞过的视频（替代收藏功能）...")
        return await self.get_liked_posts(limit)
            
    async def _apply_rate_limiting(self) -> None:
        """应用速率限制."""
        current_time = datetime.now()
        
        # 检查是否需要重置计数器
        if (current_time - self._rate_limit_start).total_seconds() > self.rate_limit_window:
            self._request_count = 0
            self._rate_limit_start = current_time
            
        # 检查请求间隔
        time_since_last = (current_time - self._last_request_time).total_seconds()
        if time_since_last < self.request_delay:
            wait_time = self.request_delay - time_since_last
            logger.debug(f"应用速率限制，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)
            
        self._request_count += 1
        self._last_request_time = datetime.now()
        
    async def test_connection(self) -> bool:
        """测试连接."""
        try:
            return await self.initialize()
        except Exception as e:
            logger.error(f"连接测试失败: {e}")
            return False
            
    async def close(self) -> None:
        """关闭客户端."""
        await self._close_session()
        logger.info("Instagram客户端已关闭")