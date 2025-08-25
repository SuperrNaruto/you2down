"""Telegram Bot通知模块."""

import asyncio
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from database import VideoInfo


class TelegramNotifier:
    """Telegram通知器."""
    
    def __init__(self, bot_token: str, chat_id: int):
        """初始化Telegram通知器."""
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=bot_token)
        self.dp = Dispatcher()
        self.retry_callback: Optional[Callable[[str], None]] = None
        # 跟踪每个视频的消息ID，用于消息删除功能
        self.video_messages: Dict[str, List[int]] = {}
        self._setup_handlers()
    
    def _setup_handlers(self) -> None:
        """设置消息处理器."""
        
        @self.dp.message(Command("start"))
        async def start_handler(message: Message) -> None:
            """处理/start命令."""
            await message.answer(
                "🎬 YouTube下载系统已启动\n"
                "📋 可用命令:\n"
                "/status - 查看系统状态\n"
                "/stats - 查看统计信息"
            )
        
        @self.dp.message(Command("status"))
        async def status_handler(message: Message) -> None:
            """处理/status命令."""
            if self.status_callback:
                status_info = await self.status_callback()
                await message.answer(status_info)
            else:
                await message.answer("❌ 状态查询功能未启用")
        
        @self.dp.message(Command("stats"))
        async def stats_handler(message: Message) -> None:
            """处理/stats命令."""
            if self.stats_callback:
                stats_info = await self.stats_callback()
                await message.answer(stats_info)
            else:
                await message.answer("❌ 统计功能未启用")
        
        @self.dp.callback_query(F.data.startswith("retry_"))
        async def retry_handler(callback_query: CallbackQuery) -> None:
            """处理重试回调."""
            video_id = callback_query.data.split("_", 1)[1]
            
            if self.retry_callback:
                try:
                    await self.retry_callback(video_id)
                    await callback_query.answer("✅ 已重新开始处理")
                    await callback_query.message.edit_text(
                        f"{callback_query.message.text}\n\n🔄 已重新开始处理"
                    )
                except Exception as e:
                    await callback_query.answer(f"❌ 重试失败: {str(e)}")
            else:
                await callback_query.answer("❌ 重试功能未启用")
    
    def set_retry_callback(self, callback: Callable[[str], None]) -> None:
        """设置重试回调函数."""
        self.retry_callback = callback
    
    def set_status_callback(self, callback: Callable[[], str]) -> None:
        """设置状态查询回调函数."""
        self.status_callback = callback
    
    def set_stats_callback(self, callback: Callable[[], str]) -> None:
        """设置统计信息回调函数."""
        self.stats_callback = callback
    
    async def start(self) -> None:
        """启动Bot（如果需要接收命令）."""
        # 注意：在这个简化版本中，我们主要用于发送通知
        # 如果需要完整的bot功能，需要在单独的任务中运行polling
        pass
    
    async def stop(self) -> None:
        """停止Bot."""
        await self.bot.session.close()
    
    async def send_message(
        self, 
        text: str, 
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> Optional[int]:
        """发送消息并返回消息ID."""
        try:
            message = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            return message.message_id
        except Exception as e:
            print(f"发送Telegram消息失败: {e}")
            return None

    async def delete_message(self, message_id: int) -> bool:
        """删除消息."""
        try:
            await self.bot.delete_message(
                chat_id=self.chat_id,
                message_id=message_id
            )
            return True
        except Exception as e:
            print(f"删除Telegram消息失败: {e}")
            return False
    
    async def delete_video_messages(self, video_id: str) -> None:
        """删除某个视频的所有相关消息."""
        if video_id in self.video_messages:
            for message_id in self.video_messages[video_id]:
                await self.delete_message(message_id)
            # 清空该视频的消息记录
            self.video_messages[video_id] = []
    
    async def notify_startup(self) -> None:
        """发送启动通知."""
        text = (
            "🚀 <b>YouTube下载系统已启动</b>\n"
            f"⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "📋 系统准备就绪，开始监控播放列表..."
        )
        await self.send_message(text)
    
    async def notify_shutdown(self) -> None:
        """发送关闭通知."""
        text = (
            "🛑 <b>YouTube下载系统已停止</b>\n"
            f"⏰ 停止时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send_message(text)
    
    async def notify_download_start(self, video_info: VideoInfo) -> None:
        """通知开始下载."""
        text = (
            "🔄 <b>开始下载</b>\n"
            f"📹 标题: {video_info.title}\n"
            f"🆔 ID: {video_info.id}\n"
            f"⏱️ 时间: {datetime.now().strftime('%H:%M:%S')}"
        )
        message_id = await self.send_message(text)
        
        # 记录消息ID
        if message_id:
            if video_info.id not in self.video_messages:
                self.video_messages[video_info.id] = []
            self.video_messages[video_info.id].append(message_id)
    
    async def notify_download_complete(self, video_info: VideoInfo) -> None:
        """通知下载完成."""
        # 删除之前的消息
        await self.delete_video_messages(video_info.id)
        
        text = (
            "✅ <b>下载完成</b>\n"
            f"📹 标题: {video_info.title}\n"
            f"🆔 ID: {video_info.id}\n"
            "⬆️ 准备上传到Alist..."
        )
        message_id = await self.send_message(text)
        
        # 记录新消息ID
        if message_id:
            if video_info.id not in self.video_messages:
                self.video_messages[video_info.id] = []
            self.video_messages[video_info.id].append(message_id)
    
    async def notify_download_failed(self, video_info: VideoInfo, error: str) -> None:
        """通知下载失败."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🔄 重试下载",
                callback_data=f"retry_{video_info.id}"
            )
        ]])
        
        text = (
            "❌ <b>下载失败</b>\n"
            f"📹 标题: {video_info.title}\n"
            f"🆔 ID: {video_info.id}\n"
            f"🔍 错误: {error}\n"
            f"🔢 重试次数: {video_info.retry_count}"
        )
        await self.send_message(text, reply_markup=keyboard)
    
    async def notify_upload_start(self, video_info: VideoInfo) -> None:
        """通知开始上传."""
        # 删除之前的消息
        await self.delete_video_messages(video_info.id)
        
        text = (
            "⬆️ <b>开始上传</b>\n"
            f"📹 标题: {video_info.title}\n"
            f"🆔 ID: {video_info.id}\n"
            f"⏱️ 时间: {datetime.now().strftime('%H:%M:%S')}"
        )
        message_id = await self.send_message(text)
        
        # 记录新消息ID
        if message_id:
            if video_info.id not in self.video_messages:
                self.video_messages[video_info.id] = []
            self.video_messages[video_info.id].append(message_id)
    
    async def notify_upload_complete(self, video_info: VideoInfo, file_url: str = "") -> None:
        """通知上传完成."""
        # 删除之前的消息
        await self.delete_video_messages(video_info.id)
        
        text = (
            "🎉 <b>处理完成</b>\n"
            f"📹 标题: {video_info.title}\n"
            f"🆔 ID: {video_info.id}\n"
            "💾 已保存到Alist"
        )
        
        # 发送最终消息，但不记录到video_messages中，因为这是最终消息，不需要删除
        await self.send_message(text)
        
        # 清理该视频的消息记录
        if video_info.id in self.video_messages:
            del self.video_messages[video_info.id]
    
    async def notify_upload_failed(self, video_info: VideoInfo, error: str) -> None:
        """通知上传失败."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🔄 重试上传",
                callback_data=f"retry_{video_info.id}"
            )
        ]])
        
        text = (
            "❌ <b>上传失败</b>\n"
            f"📹 标题: {video_info.title}\n"
            f"🆔 ID: {video_info.id}\n"
            f"🔍 错误: {error}\n"
            f"🔢 重试次数: {video_info.retry_count}"
        )
        await self.send_message(text, reply_markup=keyboard)
    
    async def notify_playlist_check(self, playlist_id: str, playlist_name: str, new_videos_count: int) -> None:
        """通知播放列表检查结果（仅在发现新视频时调用）."""
        text = (
            "📋 <b>发现新视频</b>\n"
            f"🎬 播放列表: {playlist_name}\n"
            f"📈 新视频数量: {new_videos_count}\n"
            "🔄 开始下载任务..."
        )
        await self.send_message(text)
    
    async def notify_error(self, error_type: str, error_message: str) -> None:
        """通知系统错误."""
        text = (
            "🚨 <b>系统错误</b>\n"
            f"🔍 类型: {error_type}\n"
            f"💬 消息: {error_message}\n"
            f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send_message(text)
    
    async def notify_daily_summary(self, stats: Dict[str, Any]) -> None:
        """发送每日汇总."""
        text = (
            "📊 <b>每日汇总报告</b>\n"
            f"📅 日期: {datetime.now().strftime('%Y-%m-%d')}\n"
            f"✅ 成功下载: {stats.get('completed', 0)}\n"
            f"❌ 失败任务: {stats.get('failed', 0)}\n"
            f"⏳ 待处理: {stats.get('pending', 0)}\n"
            f"🔄 处理中: {stats.get('processing', 0)}"
        )
        await self.send_message(text)
    
    async def test_connection(self) -> bool:
        """测试Bot连接."""
        try:
            await self.bot.get_me()
            return True
        except Exception as e:
            print(f"Telegram Bot连接测试失败: {e}")
            return False