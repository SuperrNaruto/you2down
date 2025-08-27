"""Google Drive链接检测模块."""

import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


@dataclass
class DriveLink:
    """Google Drive链接信息."""
    file_id: str
    original_url: str
    link_type: str  # 'file', 'document', 'spreadsheet', 'presentation'
    direct_download_url: Optional[str] = None


class GoogleDriveDetector:
    """Google Drive链接检测器."""
    
    # Google Drive链接模式
    DRIVE_PATTERNS = [
        # 标准文件分享链接（包含/view, /edit等后缀）
        r'https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)(?:/[a-zA-Z]*)?(?:\?[^&\s]*)?',
        # 旧版open链接
        r'https?://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
        # Google Docs文档
        r'https?://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)',
        # Google Sheets表格
        r'https?://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)',
        # Google Slides演示文稿
        r'https?://docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)',
        # Drive文件夹
        r'https?://drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)',
        # UC链接（直接下载）
        r'https?://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)',
        # 另一种文件链接格式
        r'https?://drive\.google\.com/(?:a/[^/]+/)?file/d/([a-zA-Z0-9_-]+)',
    ]
    
    def __init__(self):
        """初始化检测器."""
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.DRIVE_PATTERNS]
    
    def detect_drive_links(self, text: str) -> List[DriveLink]:
        """从文本中检测Google Drive链接.
        
        Args:
            text: 要检测的文本内容
            
        Returns:
            检测到的Drive链接列表
        """
        if not text:
            return []
        
        drive_links = []
        seen_file_ids = set()
        
        try:
            # 使用正则表达式匹配
            for pattern in self.compiled_patterns:
                matches = pattern.finditer(text)
                for match in matches:
                    file_id = match.group(1)
                    original_url = match.group(0)
                    
                    # 避免重复
                    if file_id in seen_file_ids:
                        continue
                    seen_file_ids.add(file_id)
                    
                    # 确定链接类型
                    link_type = self._determine_link_type(original_url)
                    
                    # 生成直接下载链接（如果适用）
                    direct_url = self._generate_direct_download_url(file_id, link_type)
                    
                    drive_link = DriveLink(
                        file_id=file_id,
                        original_url=original_url,
                        link_type=link_type,
                        direct_download_url=direct_url
                    )
                    
                    drive_links.append(drive_link)
                    logger.debug(f"检测到Drive链接: {drive_link}")
            
            # 额外处理URL参数中的链接
            drive_links.extend(self._extract_from_url_params(text, seen_file_ids))
            
        except Exception as e:
            logger.error(f"检测Drive链接时出错: {e}")
        
        logger.info(f"共检测到 {len(drive_links)} 个Google Drive链接")
        return drive_links
    
    def _determine_link_type(self, url: str) -> str:
        """确定链接类型."""
        url_lower = url.lower()
        
        if 'docs.google.com/document' in url_lower:
            return 'document'
        elif 'docs.google.com/spreadsheets' in url_lower:
            return 'spreadsheet'
        elif 'docs.google.com/presentation' in url_lower:
            return 'presentation'
        elif 'drive.google.com/drive/folders' in url_lower:
            return 'folder'
        else:
            return 'file'
    
    def _generate_direct_download_url(self, file_id: str, link_type: str) -> Optional[str]:
        """生成直接下载链接."""
        # 只为普通文件生成直接下载链接
        if link_type == 'file':
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        return None
    
    def _extract_from_url_params(self, text: str, seen_file_ids: set) -> List[DriveLink]:
        """从URL参数中提取Drive链接."""
        drive_links = []
        
        # 查找所有URL
        url_pattern = r'https?://[^\s<>"\']+drive\.google\.com[^\s<>"\']*'
        url_matches = re.finditer(url_pattern, text, re.IGNORECASE)
        
        for url_match in url_matches:
            url = url_match.group(0)
            try:
                parsed = urlparse(url)
                query_params = parse_qs(parsed.query)
                
                # 检查id参数
                if 'id' in query_params:
                    file_ids = query_params['id']
                    for file_id in file_ids:
                        if file_id and file_id not in seen_file_ids:
                            seen_file_ids.add(file_id)
                            
                            drive_link = DriveLink(
                                file_id=file_id,
                                original_url=url,
                                link_type='file',
                                direct_download_url=f"https://drive.google.com/uc?export=download&id={file_id}"
                            )
                            
                            drive_links.append(drive_link)
                            
            except Exception as e:
                logger.debug(f"解析URL参数失败 {url}: {e}")
        
        return drive_links
    
    def is_valid_file_id(self, file_id: str) -> bool:
        """验证文件ID格式."""
        if not file_id or len(file_id) < 10:
            return False
        
        # Google Drive文件ID通常是字母数字和少数特殊字符
        pattern = r'^[a-zA-Z0-9_-]+$'
        return bool(re.match(pattern, file_id))
    
    def extract_file_id_from_url(self, url: str) -> Optional[str]:
        """从URL中提取文件ID."""
        for pattern in self.compiled_patterns:
            match = pattern.search(url)
            if match:
                return match.group(1)
        return None


def test_detector():
    """测试检测器功能."""
    detector = GoogleDriveDetector()
    
    test_texts = [
        "下载地址：https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/view?usp=sharing",
        "文档链接 https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit",
        "老版本链接：https://drive.google.com/open?id=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
        "多个链接：\nhttps://drive.google.com/file/d/123abc/view\nhttps://docs.google.com/spreadsheets/d/456def/edit",
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n测试 {i}: {text}")
        links = detector.detect_drive_links(text)
        for link in links:
            print(f"  - 文件ID: {link.file_id}")
            print(f"    类型: {link.link_type}")
            print(f"    原始URL: {link.original_url}")
            print(f"    下载URL: {link.direct_download_url}")


if __name__ == "__main__":
    test_detector()