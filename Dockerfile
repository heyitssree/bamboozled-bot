# One image, one process. VITE_DISCORD_CLIENT_ID is public (the application id); no secret is ever a build argument.
FROM node:20-slim AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
ARG VITE_DISCORD_CLIENT_ID
RUN npm run build

FROM python:3.11-slim
ARG TARGETARCH
ARG LITESTREAM_VERSION=0.3.13
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates sqlite3 \
 && curl -fsSL -o /tmp/ls.tar.gz "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-${TARGETARCH}.tar.gz" \
 && tar -C /usr/local/bin -xzf /tmp/ls.tar.gz && rm /tmp/ls.tar.gz && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bamboozled/ bamboozled/
COPY data/ data/
COPY --from=web /web/dist /app/web_dist
COPY docker/litestream.yml /etc/litestream.yml
COPY docker/entrypoint.sh /entrypoint.sh
RUN useradd -r -u 10002 bamboozled && mkdir -p /app/data && chown -R bamboozled /app/data && chmod +x /entrypoint.sh
USER bamboozled
ENV BAMBOOZLED_DB_PATH=/app/data/bamboozled.db BAMBOOZLED_PRIVACY_DB_PATH=/app/data/privacy.db BAMBOOZLED_PORT=8480
EXPOSE 8480
CMD ["/entrypoint.sh"]
