# 使用Alpine + ffmpeg，更小且稳定
FROM python:3.11-alpine

# 安装ffmpeg和构建依赖，设置时区
RUN apk add --no-cache \
    ffmpeg \
    gcc \
    musl-dev \
    libffi-dev \
    tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone

# 设置工作目录
WORKDIR /app

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY app/ ./app/

# 创建数据目录
RUN mkdir -p /app/downloads /app/data /app/logs

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 健康检查
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import asyncio; print('OK')" || exit 1

# 运行应用
CMD ["python", "app/main.py"]