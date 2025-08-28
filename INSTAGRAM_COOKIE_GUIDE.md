# Instagram Cookie导入指南

## 概述

为了解决VPS环境中无法使用浏览器手动登录Instagram的问题，系统现在支持通过cookie文件进行认证。这种方法更稳定，不容易触发Instagram的反爬虫机制。

## Cookie获取方法

### 方法一：使用浏览器插件（推荐）

1. **安装Chrome插件**：
   - 推荐插件：`Cookie-Editor` 或 `EditThisCookie`
   - 或者搜索任何能导出JSON格式cookie的插件

2. **导出步骤**：
   - 在Chrome中登录Instagram
   - 访问 https://www.instagram.com
   - 打开插件，选择导出为JSON格式
   - 保存文件为 `instagram_cookies.json`

### 方法二：使用浏览器开发者工具

1. **获取Cookie**：
   - 在Chrome中登录Instagram
   - 按F12打开开发者工具
   - 转到 `Application` 标签页
   - 左侧选择 `Cookies` → `https://www.instagram.com`
   - 找到并复制这些关键cookie：
     - `sessionid`（必需）
     - `csrftoken`（必需）
     - `ds_user_id`（推荐）

2. **创建Cookie文件**：
```json
[
  {
    "name": "sessionid",
    "value": "你的sessionid值",
    "domain": ".instagram.com",
    "path": "/",
    "secure": true,
    "httpOnly": true
  },
  {
    "name": "csrftoken",
    "value": "你的csrftoken值",
    "domain": ".instagram.com",
    "path": "/",
    "secure": true,
    "httpOnly": false
  },
  {
    "name": "ds_user_id",
    "value": "你的用户ID",
    "domain": ".instagram.com",
    "path": "/",
    "secure": true,
    "httpOnly": false
  }
]
```

## 支持的Cookie格式

系统支持三种cookie格式：

### 1. JSON数组格式（推荐）
```json
[
  {
    "name": "sessionid",
    "value": "sessionid_value_here",
    "domain": ".instagram.com",
    "path": "/",
    "secure": true,
    "httpOnly": true
  }
]
```

### 2. Netscape格式
```
# Netscape HTTP Cookie File
.instagram.com	TRUE	/	TRUE	1700000000	sessionid	sessionid_value_here
.instagram.com	TRUE	/	FALSE	1700000000	csrftoken	csrftoken_value_here
```

### 3. 简单键值对格式
```
sessionid=sessionid_value_here; csrftoken=csrftoken_value_here; ds_user_id=user_id_here
```

## 部署配置

### 环境变量配置

在`.env`文件中添加：

```bash
# Instagram配置
ENABLE_INSTAGRAM=true
INSTAGRAM_COOKIE_FILE=/app/data/instagram_cookies.json

# 可选：如果cookie失效，可以配置用户名密码作为备用
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
INSTAGRAM_SESSION_FILE=/app/data/instagram_session.json
```

### Docker部署

1. **将cookie文件放到数据目录**：
```bash
# 在VPS上创建数据目录
mkdir -p /path/to/your/data

# 上传cookie文件
scp instagram_cookies.json user@your-vps:/path/to/your/data/
```

2. **更新docker-compose.yml**：
```yaml
volumes:
  - /path/to/your/data:/app/data
```

3. **重启容器**：
```bash
docker-compose down
docker-compose up -d
```

## Cookie维护

### 自动检测和刷新
- 系统会自动检测cookie有效性
- 当发生401错误时会尝试重新加载cookie
- 建议每30-60天更新一次cookie文件

### 手动更新Cookie
1. 重新从浏览器导出cookie
2. 替换服务器上的cookie文件
3. 重启服务或等待自动重新加载

### 监控Cookie状态
- 查看日志中的认证状态：
```bash
docker-compose logs you2down | grep -i instagram
```

- Telegram通知会报告认证失败

## 安全建议

### Cookie保护
- **权限控制**：设置cookie文件权限为600
```bash
chmod 600 /app/data/instagram_cookies.json
```

- **定期更换**：建议每月更换一次cookie
- **备份**：保留有效的cookie备份

### 账号安全
- 不要在多个地方同时使用同一套cookie
- 定期检查Instagram账号的活动日志
- 如发现异常，立即更换密码并重新获取cookie

## 故障排除

### 常见问题

1. **"401 Unauthorized"错误**
   - 检查cookie文件是否存在且格式正确
   - 验证sessionid和csrftoken是否有效
   - 尝试重新获取cookie

2. **"无法解析cookie文件"错误**
   - 检查JSON格式是否正确
   - 确保文件编码为UTF-8
   - 验证文件权限

3. **连接超时**
   - 检查网络连接
   - 验证Instagram域名是否可访问
   - 检查防火墙设置

### 调试步骤

1. **验证cookie文件**：
```bash
# 检查文件是否存在
ls -la /app/data/instagram_cookies.json

# 验证JSON格式
cat /app/data/instagram_cookies.json | python3 -m json.tool
```

2. **测试连接**：
```bash
# 查看详细日志
docker-compose logs you2down | tail -100
```

3. **重置认证**：
```bash
# 删除旧的session文件
rm /app/data/instagram_session.json

# 重启容器
docker-compose restart you2down
```

## 认证优先级

系统按以下优先级尝试认证：
1. **Cookie文件** （推荐，最稳定）
2. **Session文件** （instaloader生成）
3. **用户名密码** （最后选择，可能触发验证）

建议主要使用cookie文件认证，其他方式作为备用。

## 注意事项

- Instagram对自动化访问有严格限制，请合理使用
- 避免频繁请求，系统已内置速率限制
- 定期监控日志，及时处理认证问题
- 保护好个人cookie信息，不要分享给他人

## 技术支持

如遇到问题，请检查：
1. 系统日志中的详细错误信息
2. Cookie文件格式和内容
3. 网络连接状态
4. Instagram账号状态

更多技术细节请参考代码注释和系统日志。