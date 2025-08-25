"""Alist API客户端模块."""

import os
import aiohttp
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from urllib.parse import quote


@dataclass
class UploadResult:
    """上传结果."""
    success: bool
    message: str = ""
    file_url: str = ""
    error: Optional[str] = None


class AlistClient:
    """Alist API客户端."""
    
    def __init__(
        self, 
        server_url: str, 
        username: str, 
        password: str,
        upload_path: str = "/videos"
    ):
        """初始化Alist客户端."""
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password
        self.upload_path = upload_path
        self.session: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None
        self._token_lock = asyncio.Lock()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
            # 添加标准headers提高兼容性
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; AlistClient/1.0)',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            }
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
                connector=aiohttp.TCPConnector(limit=100, limit_per_host=30)
            )
        return self.session
    
    async def close(self) -> None:
        """关闭客户端."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _login(self) -> Optional[str]:
        """登录获取访问令牌."""
        async with self._token_lock:
            if self._token:
                # 验证现有token是否有效
                if await self._validate_token():
                    return self._token
            
            # 执行登录
            session = await self._get_session()
            login_url = f"{self.server_url}/api/auth/login"
            
            login_data = {
                "username": self.username,
                "password": self.password
            }
            
            try:
                async with session.post(login_url, json=login_data) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("code") == 200:
                            self._token = data["data"]["token"]
                            return self._token
                        else:
                            print(f"Alist登录失败: {data.get('message', '未知错误')}")
                            return None
                    else:
                        print(f"Alist登录请求失败: {response.status}")
                        return None
            except Exception as e:
                print(f"Alist登录异常: {e}")
                return None
    
    async def _validate_token(self) -> bool:
        """验证token有效性."""
        if not self._token:
            return False
        
        session = await self._get_session()
        headers = {"Authorization": self._token}
        
        try:
            async with session.get(
                f"{self.server_url}/api/me", 
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # 检查响应体中的code字段
                    return data.get("code") == 200
                return False
        except Exception:
            return False
    
    async def _ensure_directory(self, path: str) -> bool:
        """确保目录存在."""
        # 根目录不需要创建
        if path in ["/", ""]:
            return True
            
        token = await self._login()
        if not token:
            return False
        
        session = await self._get_session()
        headers = {"Authorization": token}
        
        # 创建目录
        mkdir_url = f"{self.server_url}/api/fs/mkdir"
        mkdir_data = {"path": path}
        
        try:
            async with session.post(
                mkdir_url, 
                json=mkdir_data, 
                headers=headers
            ) as response:
                data = await response.json()
                # 目录已存在也算成功
                return data.get("code") == 200 or "already exists" in data.get("message", "")
        except Exception as e:
            print(f"创建目录失败: {e}")
            return False
    
    async def upload_file(
        self, 
        file_path: str, 
        remote_path: Optional[str] = None
    ) -> UploadResult:
        """上传文件到Alist."""
        if not os.path.exists(file_path):
            return UploadResult(
                success=False,
                error=f"文件不存在: {file_path}"
            )
        
        # 登录获取token
        token = await self._login()
        if not token:
            return UploadResult(
                success=False,
                error="Alist登录失败"
            )
        
        # 确定上传路径
        if remote_path is None:
            remote_path = self.upload_path
        
        # 确保目录存在
        if not await self._ensure_directory(remote_path):
            return UploadResult(
                success=False,
                error=f"无法创建目录: {remote_path}"
            )
        
        session = await self._get_session()
        headers = {"Authorization": token}
        
        filename = os.path.basename(file_path)
        upload_url = f"{self.server_url}/api/fs/put"
        
        try:
            # 获取文件大小
            file_size = os.path.getsize(file_path)
            
            with open(file_path, 'rb') as file:
                # 构建完整的远程路径并进行URL编码
                full_remote_path = f"{remote_path}/{filename}".replace("//", "/")
                encoded_path = quote(full_remote_path, safe='/')
                
                async with session.put(
                    upload_url,
                    headers={
                        **headers,
                        "File-Path": encoded_path,
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(file_size)
                    },
                    data=file
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        if data.get("code") == 200:
                            file_url = f"{self.server_url}{full_remote_path}"
                            return UploadResult(
                                success=True,
                                message="上传成功",
                                file_url=file_url
                            )
                        else:
                            return UploadResult(
                                success=False,
                                error=f"上传失败: {data.get('message', '未知错误')}"
                            )
                    else:
                        response_text = await response.text()
                        return UploadResult(
                            success=False,
                            error=f"HTTP错误 {response.status}: {response_text}"
                        )
                        
        except Exception as e:
            return UploadResult(
                success=False,
                error=f"上传异常: {str(e)}"
            )
    
    async def delete_file(self, remote_path: str) -> bool:
        """删除远程文件."""
        token = await self._login()
        if not token:
            return False
        
        session = await self._get_session()
        headers = {"Authorization": token}
        
        delete_url = f"{self.server_url}/api/fs/remove"
        delete_data = {"names": [os.path.basename(remote_path)], "dir": os.path.dirname(remote_path)}
        
        try:
            async with session.post(
                delete_url, 
                json=delete_data, 
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("code") == 200
                return False
        except Exception as e:
            print(f"删除文件失败: {e}")
            return False
    
    async def list_files(self, path: str = "/") -> Optional[Dict[str, Any]]:
        """列出目录文件."""
        token = await self._login()
        if not token:
            return None
        
        session = await self._get_session()
        headers = {"Authorization": token}
        
        list_url = f"{self.server_url}/api/fs/list"
        list_data = {"path": path}
        
        try:
            async with session.post(
                list_url, 
                json=list_data, 
                headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 200:
                        return data.get("data", {})
                return None
        except Exception as e:
            print(f"列出文件失败: {e}")
            return None
    
    async def test_connection(self) -> bool:
        """测试连接."""
        try:
            token = await self._login()
            return token is not None
        except Exception as e:
            print(f"测试Alist连接失败: {e}")
            return False