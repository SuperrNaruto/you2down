"""Instagram多账号管理器 - 智能账号轮换和负载均衡."""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import logging

from instagram_client import InstagramClient, InstagramMedia

logger = logging.getLogger(__name__)


@dataclass
class AccountStatus:
    """账号状态信息."""
    username: str
    is_active: bool = True
    last_used: datetime = None
    failure_count: int = 0
    rate_limit_until: Optional[datetime] = None
    total_requests: int = 0
    success_rate: float = 1.0
    
    def __post_init__(self):
        if self.last_used is None:
            self.last_used = datetime.now() - timedelta(hours=1)


class InstagramAccountManager:
    """Instagram多账号管理器 - 智能负载均衡和故障转移."""
    
    def __init__(self, accounts_config: List[Dict[str, str]], proxy_list: List[Dict[str, Any]] = None,
                 enable_ip_rotation: bool = False, max_retries: int = 5, retry_delay: int = 60):
        """初始化账号管理器."""
        self.accounts_config = accounts_config
        self.proxy_list = proxy_list or []
        self.enable_ip_rotation = enable_ip_rotation
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # 账号状态跟踪
        self.account_status = {
            config['username']: AccountStatus(username=config['username'])
            for config in accounts_config
        }
        
        # 账号客户端池
        self.clients: Dict[str, InstagramClient] = {}
        self.current_account_index = 0
        
        # 智能调度参数
        self.min_request_interval = 300  # 5分钟最小间隔
        self.max_failures_per_account = 3  # 每个账号最大失败次数
        self.cooldown_period = 3600  # 1小时冷却期
        
    async def init(self) -> None:
        """初始化所有账号客户端."""
        logger.info(f"正在初始化 {len(self.accounts_config)} 个Instagram账号...")
        
        for i, account_config in enumerate(self.accounts_config):
            try:
                username = account_config['username']
                
                # 为每个账号分配不同的代理（如果启用）
                assigned_proxy = None
                if self.proxy_list and self.enable_ip_rotation:
                    assigned_proxy = self.proxy_list[i % len(self.proxy_list)]
                
                client = InstagramClient(
                    username=account_config['username'],
                    password=account_config['password'],
                    session_file=account_config.get('session_file', f"/app/data/instagram_{username}.json"),
                    max_retries=self.max_retries,
                    retry_delay=self.retry_delay,
                    use_proxy=bool(assigned_proxy),
                    proxy_host=assigned_proxy['host'] if assigned_proxy else '',
                    proxy_port=assigned_proxy['port'] if assigned_proxy else 0,
                    proxy_list=[assigned_proxy] if assigned_proxy else [],
                    enable_ip_rotation=self.enable_ip_rotation,
                    request_delay=random.uniform(3.0, 6.0),  # 每个账号不同的请求延迟
                    rate_limit_window=300
                )
                
                await client.init()
                self.clients[username] = client
                
                logger.info(f"账号 {username} 初始化成功")
                
                # 添加随机延迟避免同时初始化
                await asyncio.sleep(random.uniform(2, 5))
                
            except Exception as e:
                logger.error(f"账号 {account_config['username']} 初始化失败: {e}")
                self.account_status[account_config['username']].is_active = False
        
        active_accounts = len([s for s in self.account_status.values() if s.is_active])
        logger.info(f"账号管理器初始化完成，活跃账号数: {active_accounts}/{len(self.accounts_config)}")
    
    def _get_best_account(self) -> Optional[str]:
        """选择最佳账号进行请求."""
        now = datetime.now()
        
        # 过滤可用账号
        available_accounts = []
        for username, status in self.account_status.items():
            if not status.is_active:
                continue
            
            # 检查是否在冷却期
            if status.rate_limit_until and now < status.rate_limit_until:
                continue
            
            # 检查失败次数
            if status.failure_count >= self.max_failures_per_account:
                # 检查是否过了冷却期
                if now - status.last_used < timedelta(seconds=self.cooldown_period):
                    continue
                else:
                    # 重置失败计数
                    status.failure_count = 0
                    logger.info(f"账号 {username} 冷却期结束，重置失败计数")
            
            available_accounts.append((username, status))
        
        if not available_accounts:
            logger.warning("没有可用的Instagram账号")
            return None
        
        # 选择策略：综合考虑最后使用时间、成功率和负载
        def account_score(account_tuple):
            username, status = account_tuple
            
            # 时间得分（越久未使用得分越高）
            time_since_last_use = (now - status.last_used).total_seconds()
            time_score = min(time_since_last_use / self.min_request_interval, 2.0)
            
            # 成功率得分
            success_score = status.success_rate
            
            # 负载得分（请求数越少得分越高）
            load_score = max(0, 2.0 - status.total_requests / 100)
            
            # 综合得分
            total_score = time_score * 0.4 + success_score * 0.4 + load_score * 0.2
            
            # 添加随机因子避免总是选择同一个账号
            random_factor = random.uniform(0.9, 1.1)
            
            return total_score * random_factor
        
        # 选择得分最高的账号
        best_account = max(available_accounts, key=account_score)
        return best_account[0]
    
    def _update_account_status(self, username: str, success: bool, error_msg: str = ""):
        """更新账号状态."""
        if username not in self.account_status:
            return
        
        status = self.account_status[username]
        status.last_used = datetime.now()
        status.total_requests += 1
        
        if success:
            # 成功请求
            if status.failure_count > 0:
                status.failure_count = max(0, status.failure_count - 1)  # 逐渐恢复
            
            # 更新成功率
            success_weight = 0.1
            status.success_rate = status.success_rate * (1 - success_weight) + success_weight
            
        else:
            # 失败请求
            status.failure_count += 1
            
            # 更新成功率
            failure_weight = 0.2
            status.success_rate = status.success_rate * (1 - failure_weight)
            
            # 检查是否需要设置冷却期
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                # 401错误设置较长冷却期
                status.rate_limit_until = datetime.now() + timedelta(seconds=1800)  # 30分钟
                logger.warning(f"账号 {username} 遇到401错误，设置30分钟冷却期")
            
            elif "429" in error_msg or "too many requests" in error_msg.lower():
                # 429错误设置冷却期
                status.rate_limit_until = datetime.now() + timedelta(seconds=3600)  # 1小时
                logger.warning(f"账号 {username} 遇到429错误，设置1小时冷却期")
            
            elif status.failure_count >= self.max_failures_per_account:
                # 失败次数过多，临时禁用
                status.rate_limit_until = datetime.now() + timedelta(seconds=self.cooldown_period)
                logger.warning(f"账号 {username} 失败次数过多，进入冷却期")
    
    async def get_saved_media(self, limit: int = 50) -> List[InstagramMedia]:
        """使用最佳账号获取收藏内容."""
        for attempt in range(len(self.clients) + 1):  # 最多尝试所有账号+1次
            username = self._get_best_account()
            if not username:
                logger.error("没有可用的Instagram账号")
                raise RuntimeError("所有Instagram账号都不可用")
            
            client = self.clients.get(username)
            if not client:
                logger.error(f"账号 {username} 的客户端不存在")
                self._update_account_status(username, False, "client_not_found")
                continue
            
            try:
                logger.info(f"使用账号 {username} 获取Instagram收藏 (尝试 {attempt + 1})")
                
                # 执行请求
                result = await client.get_saved_media(limit)
                
                # 更新成功状态
                self._update_account_status(username, True)
                logger.info(f"账号 {username} 成功获取 {len(result)} 个收藏视频")
                
                return result
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"账号 {username} 获取收藏失败: {error_msg}")
                
                # 更新失败状态
                self._update_account_status(username, False, error_msg)
                
                # 如果是最后一次尝试，抛出异常
                if attempt == len(self.clients):
                    logger.error(f"所有账号都尝试失败，最后错误: {error_msg}")
                    raise
                
                # 等待后尝试下一个账号
                await asyncio.sleep(random.uniform(5, 10))
        
        raise RuntimeError("所有Instagram账号都获取收藏失败")
    
    def get_status_report(self) -> Dict[str, Any]:
        """获取账号状态报告."""
        now = datetime.now()
        
        report = {
            'total_accounts': len(self.accounts_config),
            'active_accounts': 0,
            'cooling_down': 0,
            'failed_accounts': 0,
            'accounts': {}
        }
        
        for username, status in self.account_status.items():
            account_info = {
                'is_active': status.is_active,
                'failure_count': status.failure_count,
                'success_rate': f"{status.success_rate:.2%}",
                'total_requests': status.total_requests,
                'last_used': status.last_used.strftime("%H:%M:%S") if status.last_used else "从未",
                'status': 'unknown'
            }
            
            if not status.is_active:
                account_info['status'] = 'disabled'
                report['failed_accounts'] += 1
            elif status.rate_limit_until and now < status.rate_limit_until:
                remaining = (status.rate_limit_until - now).total_seconds()
                account_info['status'] = f'cooling ({int(remaining/60)}min)'
                report['cooling_down'] += 1
            elif status.failure_count >= self.max_failures_per_account:
                account_info['status'] = 'failed'
                report['failed_accounts'] += 1
            else:
                account_info['status'] = 'active'
                report['active_accounts'] += 1
            
            report['accounts'][username] = account_info
        
        return report
    
    async def close(self) -> None:
        """关闭所有客户端."""
        logger.info("正在关闭所有Instagram客户端...")
        
        close_tasks = []
        for username, client in self.clients.items():
            close_tasks.append(client.close())
        
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        
        logger.info(f"已关闭 {len(self.clients)} 个Instagram客户端")