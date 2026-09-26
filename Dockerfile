# 古籍残页转写拼接 API
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # /api/align 同时允许运行或清理中的子进程数（无空位立即 503、不排队）
    ALIGN_MAX_PROCESSES=2 \
    # /api/align 从接纳起的最长计算秒数（超时 504 并终止回收子进程）
    ALIGN_TIMEOUT_SECONDS=10

WORKDIR /app

# 依赖安装纳入镜像构建（启动时无需再安装）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码（uvicorn 启动时导入 app.main，期间校验上述两项配置，
# 非法正整数值会使启动直接失败）
COPY app ./app

EXPOSE 8000

# exec 形式启动：Python/uvicorn 作为容器 1 号进程接收信号，
# 关闭时触发 lifespan，终止并回收全部在运 align 子进程
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
