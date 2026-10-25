FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

# Runtime libraries for the Camoufox (Firefox) browser
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    tini \
    && rm -rf /var/lib/apt/lists/*

COPY ./app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Fetch camoufox browser
RUN python -m camoufox fetch

COPY ./app ./
COPY --from=web /web/dist ./static

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    DATA_DIR=/data \
    PORT=7477 \
    PYTHONUNBUFFERED=1

VOLUME /data
EXPOSE 7477
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# tini reaps the browser helper processes that outlive each job
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "server.py"]
