"""YouTube API客户端模块."""

import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from database import VideoInfo, PlaylistInfo


@dataclass
class YouTubeVideo:
    """YouTube视频信息."""
    id: str
    title: str
    url: str
    published_at: datetime
    description: str = ""
    thumbnail_url: str = ""


class YouTubeClient:
    """YouTube API客户端."""
    
    def __init__(self, api_key: str):
        """初始化YouTube客户端."""
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self) -> None:
        """关闭客户端."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _make_request(
        self, 
        endpoint: str, 
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """发起API请求."""
        params["key"] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"YouTube API请求失败: {response.status} - {await response.text()}")
                    return None
        except Exception as e:
            print(f"YouTube API请求异常: {e}")
            return None
    
    async def get_playlist_info(self, playlist_id: str) -> Optional[PlaylistInfo]:
        """获取播放列表信息."""
        params = {
            "part": "snippet,contentDetails",
            "id": playlist_id
        }
        
        response = await self._make_request("playlists", params)
        if not response or not response.get("items"):
            return None
        
        item = response["items"][0]
        snippet = item["snippet"]
        
        return PlaylistInfo(
            id=playlist_id,
            title=snippet.get("title", ""),
            last_checked=datetime.now(timezone.utc)
        )
    
    async def get_playlist_videos(
        self, 
        playlist_id: str, 
        max_results: int = 50
    ) -> List[YouTubeVideo]:
        """获取播放列表中的视频."""
        videos = []
        next_page_token = None
        
        while len(videos) < max_results:
            params = {
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": min(50, max_results - len(videos))
            }
            
            if next_page_token:
                params["pageToken"] = next_page_token
            
            response = await self._make_request("playlistItems", params)
            if not response or not response.get("items"):
                break
            
            for item in response["items"]:
                snippet = item["snippet"]
                video_id = snippet["resourceId"]["videoId"]
                
                # 解析发布时间
                published_at = datetime.fromisoformat(
                    snippet["publishedAt"].replace("Z", "+00:00")
                )
                
                video = YouTubeVideo(
                    id=video_id,
                    title=snippet.get("title", ""),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    published_at=published_at,
                    description=snippet.get("description", ""),
                    thumbnail_url=snippet.get("thumbnails", {}).get("default", {}).get("url", "")
                )
                videos.append(video)
            
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
        
        return videos
    
    async def get_new_videos(
        self, 
        playlist_id: str, 
        last_checked: Optional[datetime] = None
    ) -> List[VideoInfo]:
        """获取播放列表中的新视频."""
        try:
            # 获取播放列表视频
            youtube_videos = await self.get_playlist_videos(playlist_id)
            if not youtube_videos:
                return []
            
            new_videos = []
            for yt_video in youtube_videos:
                # 如果指定了上次检查时间，只返回新发布的视频
                if last_checked and yt_video.published_at <= last_checked:
                    continue
                
                video_info = VideoInfo(
                    id=yt_video.id,
                    title=yt_video.title,
                    url=yt_video.url,
                    playlist_id=playlist_id,
                    status="pending",
                    description=yt_video.description  # 添加视频描述用于Drive链接检测
                )
                new_videos.append(video_info)
            
            return new_videos
            
        except Exception as e:
            print(f"获取新视频失败: {e}")
            return []
    
    async def get_video_info(self, video_id: str) -> Optional[YouTubeVideo]:
        """获取单个视频信息."""
        params = {
            "part": "snippet",
            "id": video_id
        }
        
        response = await self._make_request("videos", params)
        if not response or not response.get("items"):
            return None
        
        item = response["items"][0]
        snippet = item["snippet"]
        
        # 解析发布时间
        published_at = datetime.fromisoformat(
            snippet["publishedAt"].replace("Z", "+00:00")
        )
        
        return YouTubeVideo(
            id=video_id,
            title=snippet.get("title", ""),
            url=f"https://www.youtube.com/watch?v={video_id}",
            published_at=published_at,
            description=snippet.get("description", ""),
            thumbnail_url=snippet.get("thumbnails", {}).get("default", {}).get("url", "")
        )
    
    async def validate_api_key(self) -> bool:
        """验证API密钥有效性."""
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "maxResults": 1
        }
        
        response = await self._make_request("videos", params)
        return response is not None
    
    async def validate_playlist(self, playlist_id: str) -> bool:
        """验证播放列表是否存在."""
        playlist_info = await self.get_playlist_info(playlist_id)
        return playlist_info is not None