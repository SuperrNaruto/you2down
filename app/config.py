"""配置管理模块."""

from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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