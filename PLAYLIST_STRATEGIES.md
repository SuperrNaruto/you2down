# 播放列表下载策略功能

## 功能概述

系统现在支持为不同的YouTube播放列表配置不同的下载策略，您可以选择：

- **仅下载视频** - 专注于视频内容，忽略Google Drive分享链接
- **仅下载分享链接** - 只获取Google Drive文件，跳过视频下载
- **全部下载** - 既下载视频又下载Google Drive文件

这个功能让您能够根据不同播放列表的内容特点，采用最适合的下载策略。

## 支持的策略类型

### 1. both（全部下载）
- **默认策略**，适用于所有未指定策略的播放列表
- 下载YouTube视频到本地
- 检测并下载视频描述中的Google Drive文件
- 完整获取播放列表的所有内容

**适用场景**：
- 综合性频道，既有视频又有配套资源
- 完整的课程系列，需要视频和讲义
- 包含教程和源码的技术频道

### 2. video_only（仅下载视频）
- 只下载YouTube视频，忽略Google Drive链接
- 视频状态设为 `pending`，正常处理
- Google Drive状态设为 `ignored`，跳过处理
- 节省带宽和存储空间

**适用场景**：
- 纯视频内容的频道（如电影、音乐、娱乐）
- 不需要额外资源的教程频道
- 带宽有限，只需要视频内容

### 3. gdrive_only（仅下载分享链接）
- 跳过YouTube视频下载，只获取Google Drive文件
- 视频状态设为 `skipped_video`，不进入下载队列
- Google Drive状态设为 `detected`（如有链接）或 `none`
- 专注于获取共享的文件资源

**适用场景**：
- 主要分享文件资源的频道
- 软件、文档、素材分享频道
- 已有视频但只需要配套文件

## 配置方法

### 方法1：环境变量配置

在 `.env` 文件中设置：

```bash
# 播放列表下载策略配置
# 格式: playlist_id1:strategy1,playlist_id2:strategy2
PLAYLIST_STRATEGIES=PLxxx123:video_only,PLyyy456:gdrive_only,PLzzz789:both
```

**配置规则**：
- 用逗号分隔多个播放列表配置
- 每个配置格式为 `播放列表ID:策略`
- 未配置的播放列表自动使用 `both` 策略
- 支持空格，系统会自动去除多余空格

### 方法2：Telegram动态配置

#### 查看当前策略
```
/strategies
```
显示所有播放列表的当前下载策略

#### 设置单个播放列表策略
```
/set_strategy PLxxx123 video_only
```

**参数说明**：
- `PLxxx123`：播放列表ID
- `video_only`：策略名称（both/video_only/gdrive_only）

**命令示例**：
```bash
/set_strategy PLxxx123 both          # 设置为全部下载
/set_strategy PLyyy456 video_only    # 设置为仅下载视频
/set_strategy PLzzz789 gdrive_only   # 设置为仅下载Drive文件
```

### 方法3：系统启动时自动应用

- 系统启动时会读取环境变量配置
- 检查播放列表时自动应用对应策略
- 如果数据库中的策略与配置不同，会自动更新

## 工作流程

### 1. 策略初始化
```
系统启动 → 读取环境配置 → 更新数据库策略 → 开始监控
```

### 2. 播放列表检查流程
```
发现新视频 → 获取播放列表策略 → 根据策略处理 → 触发相应下载事件
```

### 3. 视频处理逻辑

#### both策略处理流程：
1. 检测视频描述中的Google Drive链接
2. 视频状态设为 `pending`，加入下载队列
3. 如有Drive链接，创建Drive文件记录
4. 触发视频下载和Drive下载事件

#### video_only策略处理流程：
1. 跳过Google Drive链接检测
2. 视频状态设为 `pending`，加入下载队列
3. Google Drive状态设为 `ignored`
4. 只触发视频下载事件

#### gdrive_only策略处理流程：
1. 检测视频描述中的Google Drive链接
2. 视频状态设为 `skipped_video`，跳过视频下载
3. 如有Drive链接，创建Drive文件记录
4. 只触发Drive下载事件

## 数据库架构

### 播放列表表扩展
```sql
ALTER TABLE playlists ADD COLUMN download_strategy TEXT DEFAULT 'both';
```

### PlaylistInfo数据类
```python
@dataclass
class PlaylistInfo:
    id: str
    title: Optional[str] = None
    last_checked: Optional[datetime] = None
    last_video_count: int = 0
    download_strategy: str = "both"  # 新增字段
```

### 新增数据库操作
- `set_playlist_strategy(playlist_id, strategy)` - 设置策略
- `get_playlist_strategy(playlist_id)` - 获取策略
- `get_all_playlist_strategies()` - 获取所有策略

## Telegram通知增强

### 带策略信息的检查通知
```
📋 播放列表检查完成

📂 列表: 技术教程频道
🆔 ID: PLxxx123
🔢 新视频: 3 个
📥 策略: 仅视频
```

### 新增Telegram命令
- `/strategies` - 查看所有播放列表策略
- `/set_strategy <playlist_id> <strategy>` - 动态设置策略

## 实际使用示例

### 场景1：混合内容管理
```bash
# 配置不同类型的播放列表
PLAYLIST_STRATEGIES=PL_tutorials:both,PL_movies:video_only,PL_resources:gdrive_only
```

- `PL_tutorials`：技术教程，需要视频和配套文件
- `PL_movies`：电影频道，只需要视频
- `PL_resources`：资源分享，只需要文件

### 场景2：动态策略调整
```bash
# 通过Telegram动态调整
/set_strategy PLxxx123 gdrive_only  # 临时只获取新分享的文件
/set_strategy PLyyy456 video_only   # 暂停Drive文件下载，节省空间
```

### 场景3：分阶段处理
```bash
# 第一阶段：快速获取视频
PLAYLIST_STRATEGIES=PLxxx:video_only,PLyyy:video_only

# 第二阶段：补充获取资源文件
PLAYLIST_STRATEGIES=PLxxx:gdrive_only,PLyyy:gdrive_only
```

## 状态跟踪

### 视频状态
- `pending` - 待下载（video_only和both策略）
- `skipped_video` - 跳过视频下载（gdrive_only策略）
- 其他状态：`downloading`, `completed`, `failed` 等

### Google Drive状态
- `none` - 无Drive链接
- `detected` - 检测到Drive链接（both和gdrive_only策略）
- `ignored` - 忽略Drive链接（video_only策略）
- 其他状态：`downloading`, `completed`, `failed` 等

## 性能优化

### 带宽优化
- `video_only`策略避免不必要的Drive文件下载
- `gdrive_only`策略跳过大文件视频下载
- 根据网络状况灵活调整策略

### 存储优化
- 选择性下载减少存储空间占用
- 可按需调整策略，避免存储空间不足
- 支持临时策略变更应对突发情况

### 处理优化
- 不同策略的任务分别排队处理
- 减少不必要的检测和处理开销
- 智能事件触发机制

## 监控和调试

### 日志输出
```
播放列表 PLxxx123 发现 2 个新视频（策略: video_only）
更新播放列表 PLyyy456 下载策略为: gdrive_only
🎯 触发视频下载事件，数量: 2
🔗 触发Google Drive下载事件，待下载文件: 5
```

### Telegram反馈
- 策略变更确认通知
- 处理结果中包含策略信息
- 错误处理时的策略上下文

## 故障排除

### 常见问题

1. **策略不生效**
   - 检查配置格式是否正确
   - 确认播放列表ID是否匹配
   - 重启系统应用新配置

2. **命令解析失败**
   - 检查命令格式：`/set_strategy <id> <strategy>`
   - 确认策略名称：`both`, `video_only`, `gdrive_only`
   - 验证播放列表ID存在

3. **策略冲突**
   - Telegram命令优先级高于环境配置
   - 数据库存储实时生效
   - 可通过`/strategies`查看当前状态

### 调试方法
- 使用`/strategies`命令查看当前所有策略
- 查看系统日志中的策略应用信息
- 通过测试脚本验证配置解析

## 最佳实践

### 1. 策略规划
- **分析内容特点**：了解播放列表的内容类型
- **评估资源需求**：考虑带宽和存储限制
- **制定策略组合**：不同类型采用不同策略

### 2. 配置管理
- **使用环境变量**：适合固定配置
- **结合Telegram命令**：适合临时调整
- **定期评估**：根据使用情况优化策略

### 3. 监控运维
- **关注通知**：及时了解策略执行情况
- **查看统计**：通过`/stats`了解处理效果
- **调整策略**：根据实际需要灵活变更

这个播放列表下载策略功能为系统提供了高度的灵活性，让您能够精确控制每个播放列表的处理方式，优化资源使用和提高处理效率。