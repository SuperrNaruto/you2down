"""配置管理模块."""

from typing import List, Dict, Optional, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class Settings(BaseSettings):
    """应用程序配置类."""
    
    # 必需配置
    youtube_api_key: str = Field(..., description="YouTube API密钥")
    bot_token: str = Field(..., description="Telegram Bot Token")
    chat_id: int = Field(..., description="Telegram Chat ID")
    alist_server: str = Field(..., description="Alist服务器地址")
    alist_username: str = Field(..., description="Alist用户名")
    alist_password: str = Field(..., description="Alist密码")
    playlists: str = Field(..., description="YouTube播放列表ID列表，逗号分隔")
    
    def get_playlists_list(self) -> List[str]:
        """获取播放列表ID列表."""
        return [item.strip() for item in self.playlists.split(',') if item.strip()]
    
    def get_playlist_strategies(self) -> Dict[str, str]:
        """获取播放列表下载策略配置.
        
        Returns:
            Dict[playlist_id, strategy] 其中strategy可以是:
            - 'both': 下载视频和Drive文件（默认）
            - 'video_only': 仅下载视频
            - 'gdrive_only': 仅下载Google Drive文件
        """
        strategies = {}
        
        # 解析播放列表策略配置
        if hasattr(self, 'playlist_strategies') and self.playlist_strategies:
            # 格式: "playlist_id1:strategy1,playlist_id2:strategy2"
            for item in self.playlist_strategies.split(','):
                if ':' in item:
                    playlist_id, strategy = item.strip().split(':', 1)
                    strategies[playlist_id.strip()] = strategy.strip()
        
        # 为所有播放列表设置默认策略
        for playlist_id in self.get_playlists_list():
            if playlist_id not in strategies:
                strategies[playlist_id] = 'both'  # 默认策略
        
        return strategies
    
    def get_playlist_strategy(self, playlist_id: str) -> str:
        """获取指定播放列表的下载策略."""
        strategies = self.get_playlist_strategies()
        return strategies.get(playlist_id, 'both')
    
    # 可选配置
    check_interval: int = Field(1800, description="检查间隔(秒), 默认30分钟")
    max_concurrent_downloads: int = Field(3, description="最大并发下载数")
    download_path: str = Field("/app/downloads", description="下载目录")
    alist_path: str = Field("/videos", description="Alist上传路径")
    
    # 视频质量配置
    video_quality: str = Field("best", description="视频质量: best(最高质量), 4k, 1080p, 720p, 480p")
    
    # 数据库配置
    database_path: str = Field("/app/data/app.db", description="SQLite数据库路径")
    
    # 日志配置
    log_level: str = Field("INFO", description="日志级别")
    log_file: str = Field("/app/logs/app.log", description="日志文件路径")
    
    
    # Google Drive配置
    enable_gdrive_download: bool = Field(True, description="启用Google Drive下载功能")
    gdrive_download_path: str = Field("/app/downloads/gdrive", description="Google Drive文件下载路径")
    max_gdrive_file_size: int = Field(1073741824, description="Google Drive最大文件大小限制（字节），默认1GB")
    max_gdrive_concurrent: int = Field(2, description="Google Drive最大并发下载数")
    gdrive_upload_to_alist: bool = Field(True, description="将下载的Google Drive文件上传到Alist")
    
    # 播放列表下载策略配置
    playlist_strategies: str = Field("", description="播放列表下载策略配置，格式: playlist_id1:strategy1,playlist_id2:strategy2")
    
    # Instagram配置
    enable_instagram: bool = Field(False, description="启用Instagram收藏视频下载功能")
    instagram_username: str = Field("", description="Instagram用户名")
    instagram_password: str = Field("", description="Instagram密码")
    instagram_session_file: str = Field("/app/data/instagram_session.json", description="Instagram会话文件路径")
    instagram_cookie_file: str = Field("/app/data/instagram_cookies.json", description="Instagram Cookie文件路径")
    instagram_download_path: str = Field("/app/downloads/instagram", description="Instagram下载目录")
    instagram_check_interval: int = Field(3600, description="Instagram收藏检查间隔(秒)，默认1小时")
    max_instagram_concurrent: int = Field(2, description="Instagram最大并发下载数")
    instagram_upload_to_alist: bool = Field(True, description="将下载的Instagram视频上传到Alist")
    instagram_quality: str = Field("best", description="Instagram视频质量: best, 720p, 480p")
    
    # Instagram简化配置
    instagram_max_retries: int = Field(5, description="Instagram API最大重试次数")
    instagram_retry_delay: int = Field(60, description="Instagram重试延迟基数(秒)")
    instagram_custom_user_agent: str = Field("", description="Instagram自定义用户代理字符串")
    instagram_request_delay: float = Field(2.0, description="Instagram请求间隔延迟(秒)")
    instagram_rate_limit_window: int = Field(300, description="Instagram频率限制窗口时间(秒)")
    # 移除复杂的代理配置方法
    
    # 移除多账号配置方法，简化为单账号模式
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_parse_none_str="null",
        str_strip_whitespace=True,
        env_prefix="",
        # 禁用对List类型的JSON解析
        env_nested_delimiter=None,
    )