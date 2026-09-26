# 古籍残页转写拼接 API
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 依赖安装纳入镜像构建
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
