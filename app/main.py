"""YouTube视频自动下载上传系统主程序."""

import asyncio
import logging
import signal
from datetime import datetime
from pathlib import Path

from config import Settings
from database import Database
from youtube_client import YouTubeClient
from alist_client import AlistClient
from telegram_bot import TelegramNotifier
from downloader import VideoDownloader
from uploader import VideoUploader
from scheduler import TaskScheduler
from handlers.gdrive_handler import GoogleDriveHandler


class YouTubeDownloadSystem:
    """YouTube下载系统主类."""
    
    def __init__(self):
        """初始化系统."""
        self.config: Settings = None
        self.db: Database = None
        self.youtube: YouTubeClient = None
        self.alist: AlistClient = None
        self.telegram: TelegramNotifier = None
        self.downloader: VideoDownloader = None
        self.uploader: VideoUploader = None
        self.scheduler: TaskScheduler = None
        self.gdrive_handler: GoogleDriveHandler = None
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self) -> bool:
        """初始化所有组件."""
        try:
            # 加载配置
            self.config = Settings()
            
            # 创建必要的目录
            Path(self.config.download_path).mkdir(parents=True, exist_ok=True)
            Path(self.config.database_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.config.log_file).parent.mkdir(parents=True, exist_ok=True)
            
            # 配置日志
            self._setup_logging()
            
            logging.info("开始初始化YouTube下载系统")
            
            # 初始化数据库
            self.db = Database(self.config.database_path)
            await self.db.init()
            logging.info("数据库初始化完成")
            
            # 同步播放列表策略配置
            await self._sync_playlist_strategies()
            logging.info("播放列表策略同步完成")
            
            # 初始化YouTube客户端
            self.youtube = YouTubeClient(self.config.youtube_api_key)
            if not await self.youtube.validate_api_key():
                logging.error("YouTube API密钥验证失败")
                return False
            logging.info("YouTube客户端初始化完成")
            
            # 初始化Alist客户端
            self.alist = AlistClient(
                self.config.alist_server,
                self.config.alist_username,
                self.config.alist_password,
                self.config.alist_path
            )
            if not await self.alist.test_connection():
                logging.error("Alist连接测试失败")
                return False
            logging.info("Alist客户端初始化完成")
            
            # 初始化Telegram Bot
            self.telegram = TelegramNotifier(
                self.config.bot_token,
                self.config.chat_id
            )
            if not await self.telegram.test_connection():
                logging.error("Telegram Bot连接测试失败")
                return False
            logging.info("Telegram Bot初始化完成")
            
            # 初始化下载器
            self.downloader = VideoDownloader(
                self.config,
                self.db,
                self.telegram
            )
            logging.info("下载管理器初始化完成")
            
            # 初始化上传器
            self.uploader = VideoUploader(
                self.config,
                self.db,
                self.alist,
                self.telegram
            )
            logging.info("上传管理器初始化完成")
            
            # 初始化Google Drive处理器
            self.gdrive_handler = GoogleDriveHandler(
                self.config,
                self.db,
                self.alist,
                self.telegram
            )
            logging.info("Google Drive处理器初始化完成")
            
            # 初始化调度器
            self.scheduler = TaskScheduler(
                self.config,
                self.db,
                self.youtube,
                self.downloader,
                self.uploader,
                self.telegram,
                self.gdrive_handler
            )
            logging.info("任务调度器初始化完成")
            
            # 设置回调函数
            self.telegram.set_retry_callback(self._handle_retry)
            self.telegram.set_status_callback(self.scheduler.get_status)
            self.telegram.set_stats_callback(self._get_stats)
            
            # 设置事件驱动回调
            self.downloader.set_download_complete_callback(
                lambda: self.scheduler._trigger_event("download_completed")
            )
            self.uploader.set_upload_complete_callback(
                lambda: self.scheduler._trigger_event("upload_completed")
            )
            
            logging.info("系统初始化完成")
            return True
            
        except Exception as e:
            logging.error(f"系统初始化失败: {e}")
            return False
    
    async def _sync_playlist_strategies(self) -> None:
        """同步播放列表策略配置到数据库."""
        try:
            # 获取环境变量中的策略配置
            env_strategies = self.config.get_playlist_strategies()
            
            # 获取数据库中的当前策略
            db_strategies = await self.db.get_all_playlist_strategies()
            
            # 检查是否需要同步
            needs_sync = False
            for playlist_id, env_strategy in env_strategies.items():
                db_strategy = db_strategies.get(playlist_id)
                if db_strategy != env_strategy:
                    needs_sync = True
                    logging.info(f"检测到播放列表策略差异 {playlist_id}: DB({db_strategy}) → ENV({env_strategy})")
                    await self.db.set_playlist_strategy(playlist_id, env_strategy)
            
            if needs_sync:
                logging.info("播放列表策略已同步到数据库")
            else:
                logging.debug("播放列表策略已是最新，无需同步")
                
        except Exception as e:
            logging.error(f"同步播放列表策略失败: {e}")
    
    def _setup_logging(self) -> None:
        """配置日志."""
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config.log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        # 设置第三方库日志级别
        logging.getLogger('aiohttp').setLevel(logging.WARNING)
        logging.getLogger('aiogram').setLevel(logging.WARNING)
        logging.getLogger('apscheduler').setLevel(logging.WARNING)
    
    async def _handle_retry(self, video_id: str) -> None:
        """处理重试请求."""
        try:
            video = await self.db.get_video(video_id)
            if not video:
                return
            
            if video.status == "failed":
                if video.file_path:
                    # 重试上传
                    await self.uploader.retry_upload(video_id)
                else:
                    # 重试下载
                    await self.downloader.retry_download(video_id)
            
        except Exception as e:
            logging.error(f"处理重试请求失败: {e}")
    
    async def _get_stats(self) -> str:
        """获取统计信息."""
        try:
            return await self.scheduler.get_status()
        except Exception as e:
            return f"获取统计信息失败: {e}"
    
    async def start(self) -> None:
        """启动系统."""
        try:
            logging.info("启动YouTube下载系统")
            
            # 启动Telegram Bot
            await self.telegram.start()
            
            # 发送启动通知
            await self.telegram.notify_startup()
            
            # 启动调度器
            await self.scheduler.start()
            
            logging.info("系统启动完成")
            
        except Exception as e:
            logging.error(f"系统启动失败: {e}")
            raise
    
    async def stop(self) -> None:
        """停止系统."""
        try:
            logging.info("正在停止YouTube下载系统")
            
            # 停止调度器
            if self.scheduler:
                await self.scheduler.stop()
            
            # 发送停止通知
            if self.telegram:
                await self.telegram.notify_shutdown()
                await self.telegram.stop()
            
            # 关闭处理器
            if self.gdrive_handler:
                await self.gdrive_handler.close()
            
            # 关闭客户端连接
            if self.youtube:
                await self.youtube.close()
            
            if self.alist:
                await self.alist.close()
            
            logging.info("系统已完全停止")
            
        except Exception as e:
            logging.error(f"系统停止时出错: {e}")
    
    async def run(self) -> None:
        """运行系统主循环."""
        try:
            # 设置信号处理
            def signal_handler(signum, frame):
                logging.info(f"收到信号 {signum}，准备停止系统")
                self._shutdown_event.set()
            
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            # 启动系统
            await self.start()
            
            # 等待关闭信号
            await self._shutdown_event.wait()
            
        except KeyboardInterrupt:
            logging.info("收到键盘中断信号")
        except Exception as e:
            logging.error(f"系统运行时出错: {e}")
        finally:
            await self.stop()
    
    async def validate_configuration(self) -> bool:
        """验证配置."""
        try:
            logging.info("验证系统配置")
            
            # 验证播放列表
            for playlist_id in self.config.get_playlists_list():
                if not await self.youtube.validate_playlist(playlist_id):
                    logging.error(f"播放列表验证失败: {playlist_id}")
                    return False
            
            # 验证上传路径
            if not await self.uploader.validate_upload_path():
                logging.error("上传路径验证失败")
                return False
            
            logging.info("配置验证完成")
            return True
            
        except Exception as e:
            logging.error(f"配置验证失败: {e}")
            return False


async def main():
    """主函数."""
    system = YouTubeDownloadSystem()
    
    try:
        # 初始化系统
        if not await system.initialize():
            logging.error("系统初始化失败，退出")
            return 1
        
        # 验证配置
        if not await system.validate_configuration():
            logging.error("配置验证失败，退出")
            return 1
        
        # 运行系统
        await system.run()
        
        return 0
        
    except Exception as e:
        logging.error(f"系统运行失败: {e}")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        exit(exit_code)
    except Exception as e:
        print(f"程序启动失败: {e}")
        exit(1)