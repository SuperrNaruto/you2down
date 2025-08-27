"""Instagram客户端模块 - 用于获取收藏的视频信息."""

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
                 proxy_host: str = "", proxy_port: int = 0, custom_user_agent: str = "",
                 request_delay: float = 2.0, rate_limit_window: int = 300,
                 proxy_list: Optional[List[Dict[str, Any]]] = None, enable_ip_rotation: bool = False):
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
        self.request_delay = request_delay
        self.rate_limit_window = rate_limit_window
        self.proxy_list = proxy_list or []
        self.enable_ip_rotation = enable_ip_rotation
        self.current_proxy_index = 0
        self.proxy_failure_count = {}
        self.session = None
        self._loader = None
        self._session_valid = False
        self._last_session_check = datetime.now() - timedelta(hours=2)
        self._last_request_time = datetime.now() - timedelta(minutes=5)
        self._request_count = 0
        self._rate_limit_start = datetime.now()
        self._request_pattern_randomizer = random.Random()
        self._session_identifiers = []
        self._current_session_id = None
        
        # 更全面的User-Agent库 - 模拟不同设备和浏览器
        self.user_agents = [
            # Windows Chrome
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            # Mac Chrome
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            # Windows Edge
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/119.0.0.0 Safari/537.36",
            # Mac Safari
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
            # Linux Chrome
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0",
            # Mobile User-Agents (Instagram移动端优化)
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
        ]
        
        # 浏览器指纹元素
        self.browser_profiles = {
            'chrome_win': {
                'sec-ch-ua': '"Chromium";v="120", "Not_A Brand";v="24", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'accept-language': 'en-US,en;q=0.9',
                'accept-encoding': 'gzip, deflate, br',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
            },
            'safari_mac': {
                'accept-language': 'en-us',
                'accept-encoding': 'gzip, deflate, br',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            },
            'mobile_ios': {
                'accept-language': 'en-US,en;q=0.9',
                'accept-encoding': 'gzip, deflate, br',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
            }
        }
        
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
        """同步登录方法（增强版）."""
        try:
            if not self.username or not self.password:
                return False
            
            # 添加登录前的随机延迟
            time.sleep(random.uniform(2.0, 5.0))
            
            self._loader.login(self.username, self.password)
            
            # 保存会话（支持多身份）
            if self.session_file:
                session_dir = Path(self.session_file).parent
                session_dir.mkdir(parents=True, exist_ok=True)
                
                # 主会话文件
                self._loader.save_session_to_file(self.session_file)
                logger.info(f"会话已保存到: {self.session_file}")
                
                # 带指纹的备份会话文件
                if self._current_session_id:
                    backup_session = f"{self.session_file}.{self._current_session_id[:8]}"
                    self._loader.save_session_to_file(backup_session)
                    logger.info(f"备份会话已保存到: {backup_session}")
                
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
        """在线程池中初始化instaloader（带高级配置）."""
        try:
            import instaloader
            
            # 获取当前代理配置
            current_proxy = self._get_next_proxy()
            
            # 创建instaloader实例，配置随机用户代理
            current_ua = self._get_random_user_agent() if not self.custom_user_agent else self.custom_user_agent
            logger.debug(f"使用User-Agent: {current_ua[:50]}...")
            
            # 生成会话指纹
            if not self._current_session_id:
                self._current_session_id = self._generate_session_fingerprint()
            
            # 更高级的instaloader配置
            self._loader = instaloader.Instaloader(
                user_agent=current_ua,
                sleep=True,  # 启用请求间隔
                compress_json=True,  # 压缩会话文件
                max_connection_attempts=5,  # 增加连接尝试次数
                request_timeout=45  # 增加超时时间
            )
            
            # 设置随机请求延迟
            if hasattr(self._loader, 'context'):
                self._loader.context.sleep = random.uniform(2.0, 4.0)
            
            # 配置代理（如果启用）
            if current_proxy:
                try:
                    proxy_url = f"http://{current_proxy['host']}:{current_proxy['port']}"
                    
                    # 设置环境变量以支持代理
                    os.environ['HTTP_PROXY'] = proxy_url
                    os.environ['HTTPS_PROXY'] = proxy_url
                    os.environ['http_proxy'] = proxy_url
                    os.environ['https_proxy'] = proxy_url
                    
                    logger.info(f"已设置代理环境变量: {current_proxy['host']}:{current_proxy['port']}")
                    
                    # 为instaloader配置代理
                    proxies = {
                        'http': proxy_url,
                        'https': proxy_url
                    }
                    
                    # 异步测试代理连接（在__init_loader外部调用）
                    # 这里只是记录，实际测试需要在异步上下文中进行
                    logger.info(f"将使用代理: {proxy_url}")
                    
                except Exception as e:
                    logger.warning(f"配置代理失败: {e}")
                    if self.enable_ip_rotation:
                        self._mark_proxy_failed(self.current_proxy_index)
            
            # 尝试从会话文件加载
            if self._validate_session_file():
                try:
                    # 为会话文件添加指纹后缀以支持多身份
                    session_file_with_id = f"{self.session_file}.{self._current_session_id[:8]}"
                    
                    if Path(session_file_with_id).exists():
                        self._loader.load_session_from_file(self.username, session_file_with_id)
                        logger.info(f"从指纹会话文件加载: {session_file_with_id}")
                    else:
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
    
    async def _test_proxy_connection(self, proxy_url: str) -> bool:
        """测试代理连接是否有效（增强版）."""
        try:
            connector = aiohttp.TCPConnector(
                ssl=False,
                use_dns_cache=False,
                limit=1,
                limit_per_host=1,
                enable_cleanup_closed=True
            )
            
            # 测试多个服务以确保代理稳定性
            test_urls = [
                "http://httpbin.org/ip",
                "http://icanhazip.com",
                "http://ipecho.net/plain"
            ]
            
            success_count = 0
            for test_url in test_urls:
                try:
                    async with aiohttp.ClientSession(
                        connector=connector,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as session:
                        headers = self._get_browser_headers(random.choice(self.user_agents))
                        
                        async with session.get(
                            test_url,
                            proxy=proxy_url,
                            headers=headers
                        ) as response:
                            if response.status == 200:
                                if "httpbin" in test_url:
                                    data = await response.json()
                                    ip = data.get('origin', 'unknown')
                                else:
                                    ip = (await response.text()).strip()
                                
                                logger.info(f"代理测试成功 ({test_url}): {ip}")
                                success_count += 1
                                break  # 有一个成功就够了
                            else:
                                logger.warning(f"代理测试失败 ({test_url}): HTTP {response.status}")
                                
                except Exception as e:
                    logger.warning(f"代理测试异常 ({test_url}): {e}")
                    continue
            
            if success_count > 0:
                logger.info(f"代理连接测试通过: {success_count}/{len(test_urls)} 个测试成功")
                return True
            else:
                logger.error("代理连接测试失败: 所有测试都未通过")
                return False
                        
        except Exception as e:
            logger.error(f"代理连接测试严重失败: {e}")
            return False
    
    async def _check_rate_limit(self) -> None:
        """智能请求频率限制."""
        now = datetime.now()
        
        # 检查是否需要重置计数器
        if now - self._rate_limit_start > timedelta(seconds=self.rate_limit_window):
            self._request_count = 0
            self._rate_limit_start = now
        
        # 计算动态延迟（基于请求历史）
        time_since_last = (now - self._last_request_time).total_seconds()
        base_delay = self.request_delay
        
        # 如果最近有失败，增加延迟
        if hasattr(self, '_recent_failures') and self._recent_failures > 0:
            base_delay *= (1.5 ** min(self._recent_failures, 3))  # 最多增加3.375倍
        
        # 如果请求过于频繁，等待
        if time_since_last < base_delay:
            wait_time = base_delay - time_since_last
            # 添加小幅随机变化
            wait_time *= random.uniform(0.8, 1.2)
            logger.debug(f"智能频率限制，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)
        
        # 更新请求时间和计数
        self._last_request_time = datetime.now()
        self._request_count += 1
        
        # 动态调整延迟策略
        requests_per_minute = self._request_count / (self.rate_limit_window / 60)
        
        if requests_per_minute > 20:  # 每分钟超过20次
            additional_delay = min(60, (requests_per_minute - 20) * 2)  # 逐渐增加延迟
            logger.warning(f"高频请求检测，额外等待 {additional_delay:.1f} 秒 (RPM: {requests_per_minute:.1f})")
            await asyncio.sleep(additional_delay)
        elif requests_per_minute > 10:  # 每分钟超过10次
            additional_delay = random.uniform(1, 5)  # 小幅随机延迟
            logger.debug(f"中频请求，随机等待 {additional_delay:.1f} 秒")
            await asyncio.sleep(additional_delay)
    
    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent."""
        return random.choice(self.user_agents)
    
    def _get_browser_headers(self, ua: str) -> Dict[str, str]:
        """根据User-Agent生成匹配的浏览器头."""
        base_headers = {
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # 根据User-Agent添加特定头部
        if 'Chrome' in ua:
            if 'Windows' in ua:
                base_headers.update(self.browser_profiles['chrome_win'])
            base_headers['sec-ch-ua'] = '"Chromium";v="120", "Not_A Brand";v="24", "Google Chrome";v="120"'
            base_headers['sec-ch-ua-mobile'] = '?0'
        elif 'Safari' in ua and 'Chrome' not in ua:
            base_headers.update(self.browser_profiles['safari_mac'])
        elif 'iPhone' in ua or 'Android' in ua:
            base_headers.update(self.browser_profiles['mobile_ios'])
            if 'iPhone' in ua:
                base_headers['sec-ch-ua-mobile'] = '?1'
        
        return base_headers
    
    def _get_next_proxy(self) -> Optional[Dict[str, Any]]:
        """获取下一个可用代理."""
        if not self.proxy_list or not self.enable_ip_rotation:
            if self.use_proxy and self.proxy_host and self.proxy_port:
                return {
                    'host': self.proxy_host,
                    'port': self.proxy_port,
                    'type': 'http'
                }
            return None
        
        # 找到失败次数最少的代理
        best_proxy = None
        min_failures = float('inf')
        
        for i, proxy in enumerate(self.proxy_list):
            failures = self.proxy_failure_count.get(i, 0)
            if failures < min_failures:
                min_failures = failures
                best_proxy = proxy
                self.current_proxy_index = i
        
        return best_proxy
    
    def _mark_proxy_failed(self, proxy_index: int) -> None:
        """标记代理失败."""
        self.proxy_failure_count[proxy_index] = self.proxy_failure_count.get(proxy_index, 0) + 1
        logger.warning(f"代理 {proxy_index} 失败次数: {self.proxy_failure_count[proxy_index]}")
    
    def _reset_proxy_failures(self) -> None:
        """重置所有代理的失败计数."""
        self.proxy_failure_count.clear()
        logger.info("已重置代理失败计数")
    
    def _generate_session_fingerprint(self) -> str:
        """生成会话指纹来模拟不同设备."""
        components = [
            str(random.randint(1000000000, 9999999999)),  # 设备ID
            str(random.randint(100000, 999999)),  # 会话ID
            str(int(time.time())),  # 时间戳
        ]
        return '_'.join(components)
    
    async def _randomize_request_timing(self) -> None:
        """随机化请求时间模式以避免检测."""
        # 基础延迟
        base_delay = self.request_delay
        
        # 添加随机变化 (±50%)
        variation = self._request_pattern_randomizer.uniform(-0.5, 0.5)
        actual_delay = base_delay * (1 + variation)
        
        # 确保最小延迟
        actual_delay = max(1.0, actual_delay)
        
        # 偶尔添加更长的暂停（模拟人类行为）
        if self._request_pattern_randomizer.random() < 0.1:  # 10%概率
            burst_delay = self._request_pattern_randomizer.uniform(5, 15)
            actual_delay += burst_delay
            logger.debug(f"人工行为模拟: 额外等待 {burst_delay:.2f} 秒")
        
        logger.debug(f"请求延迟: {actual_delay:.2f} 秒")
        await asyncio.sleep(actual_delay)
    
    async def _rotate_session_identity(self) -> None:
        """轮换会话身份."""
        # 生成新的会话指纹
        new_session_id = self._generate_session_fingerprint()
        self._current_session_id = new_session_id
        
        # 保存到历史记录
        self._session_identifiers.append({
            'id': new_session_id,
            'created_at': datetime.now(),
            'user_agent': self._get_random_user_agent()
        })
        
        # 清理旧的会话记录（保留最近20个）
        if len(self._session_identifiers) > 20:
            self._session_identifiers = self._session_identifiers[-20:]
        
        logger.info(f"已轮换会话身份: {new_session_id[:12]}...")
    
    async def _advanced_error_analysis(self, error_msg: str, attempt: int) -> Dict[str, Any]:
        """高级错误分析和策略建议."""
        analysis = {
            'error_type': 'unknown',
            'severity': 'medium',
            'suggested_actions': [],
            'wait_time': self.retry_delay * (2 ** attempt),
            'should_rotate_proxy': False,
            'should_rotate_session': False
        }
        
        error_lower = error_msg.lower()
        
        # 401未授权错误
        if "401" in error_msg or "unauthorized" in error_lower:
            analysis['error_type'] = 'authentication'
            analysis['severity'] = 'high'
            analysis['suggested_actions'].extend([
                'refresh_session', 'rotate_user_agent', 'increase_delay'
            ])
            if "wait a few minutes" in error_lower:
                analysis['wait_time'] = max(300, analysis['wait_time'])  # 最少等5分钟
                analysis['should_rotate_proxy'] = True
                analysis['should_rotate_session'] = True
        
        # 429限流错误
        elif "429" in error_msg or "too many requests" in error_lower:
            analysis['error_type'] = 'rate_limit'
            analysis['severity'] = 'high'
            analysis['wait_time'] = max(600, analysis['wait_time'])  # 最少等10分钟
            analysis['should_rotate_proxy'] = True
            analysis['suggested_actions'].extend([
                'rotate_proxy', 'increase_delay', 'rotate_session'
            ])
        
        # IP封禁
        elif "blocked" in error_lower or "banned" in error_lower:
            analysis['error_type'] = 'ip_blocked'
            analysis['severity'] = 'critical'
            analysis['wait_time'] = max(1800, analysis['wait_time'])  # 最少等30分钟
            analysis['should_rotate_proxy'] = True
            analysis['should_rotate_session'] = True
            analysis['suggested_actions'].extend([
                'rotate_proxy', 'rotate_session', 'long_delay'
            ])
        
        # 网络连接问题
        elif any(x in error_lower for x in ['connection', 'timeout', 'network']):
            analysis['error_type'] = 'network'
            analysis['severity'] = 'medium'
            analysis['suggested_actions'].extend(['retry_connection'])
        
        logger.info(f"错误分析: 类型={analysis['error_type']}, 严重度={analysis['severity']}, 建议等待={analysis['wait_time']}秒")
        return analysis
    
    async def get_saved_media(self, limit: int = 50) -> List[InstagramMedia]:
        """获取用户收藏的媒体内容（带高级重试机制）."""
        if not self._loader:
            raise RuntimeError("Instagram客户端未初始化")
            
        if not self.username:
            raise RuntimeError("获取收藏内容需要登录")
        
        # 执行请求频率控制
        await self._check_rate_limit()
        
        # 如果会话可能过期，先验证
        if self._is_session_expired() or not self._session_valid:
            await self._refresh_session_if_needed()
        
        # 带高级重试的执行
        for attempt in range(self.max_retries):
            try:
                # 随机化请求时间
                await self._randomize_request_timing()
                
                # 在线程池中执行
                func = partial(self._get_saved_media_sync, limit)
                result = await asyncio.get_event_loop().run_in_executor(
                    self.executor, func
                )
                
                # 成功后重置代理失败计数
                if attempt > 0:
                    self._reset_proxy_failures()
                
                return result
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"获取Instagram收藏失败，尝试 {attempt + 1}/{self.max_retries}: {error_msg}")
                
                # 进行高级错误分析
                error_analysis = await self._advanced_error_analysis(error_msg, attempt)
                
                # 根据错误分析执行相应策略
                if error_analysis['should_rotate_proxy'] and self.enable_ip_rotation:
                    # 标记当前代理失败并轮换
                    self._mark_proxy_failed(self.current_proxy_index)
                    new_proxy = self._get_next_proxy()
                    if new_proxy:
                        logger.info(f"轮换到新代理: {new_proxy['host']}:{new_proxy['port']}")
                        # 重新初始化loader以使用新代理
                        try:
                            await self._refresh_session_if_needed(force=True)
                        except Exception as refresh_error:
                            logger.error(f"代理轮换后刷新会话失败: {refresh_error}")
                
                if error_analysis['should_rotate_session']:
                    # 轮换会话身份
                    await self._rotate_session_identity()
                    try:
                        await self._refresh_session_if_needed(force=True)
                    except Exception as refresh_error:
                        logger.error(f"会话轮换后刷新失败: {refresh_error}")
                
                # 如果是最后一次尝试，抛出异常
                if attempt == self.max_retries - 1:
                    logger.error(f"所有高级重试均失败，获取Instagram收藏失败: {error_msg}")
                    logger.error(f"最终错误分析: {error_analysis}")
                    raise
                
                # 等待后重试，使用分析建议的等待时间
                wait_time = error_analysis['wait_time']
                logger.info(f"根据错误分析等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
    
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
        # 清理代理环境变量
        for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
            if var in os.environ:
                del os.environ[var]
        
        logger.info(f"Instagram客户端已关闭，处理了{len(self._session_identifiers)}个会话身份")


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