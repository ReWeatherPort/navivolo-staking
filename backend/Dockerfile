# 使用官方 Python 3.9 映像
FROM python:3.9-slim

# 設置工作目錄
WORKDIR /app

# 複製 requirements.txt 同代碼
COPY requirements.txt .
COPY . .

# 安裝依賴
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口
EXPOSE 5000

# 運行應用
CMD ["python", "navi_volo_api.py"]