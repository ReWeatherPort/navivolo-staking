# 建構階段：下載輪子
FROM python:3.9-slim AS builder

WORKDIR /app

# 複製 requirements.txt
COPY backend/requirements.txt .

# 安裝依賴到臨時目錄，強制用 wheel
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# 最終階段
FROM python:3.9-slim

WORKDIR /app

# 複製已安裝嘅依賴
COPY --from=builder /usr/local/lib/python3.9/site-packages/ /usr/local/lib/python3.9/site-packages/
COPY backend/ .

# 配置環境變量
ENV PATH=/usr/local/lib/python3.9/site-packages/bin:$PATH

# 暴露端口
EXPOSE 5000

# 運行應用
CMD ["python", "navi_volo_api.py"]