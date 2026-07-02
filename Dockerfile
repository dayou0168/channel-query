FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHANNEL_QUERY_DATA_DIR=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY channel_query_app.py telegram_bot.py telegram_config.example.json telegram_backend_only_config.example.json ./

RUN mkdir -p /data /config

CMD ["python", "telegram_bot.py", "--config", "/config/telegram_config.json"]
