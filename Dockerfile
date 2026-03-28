FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV SHORTMAKER_YTDLP_POT_PROVIDER=script
ENV SHORTMAKER_YTDLP_POT_SERVER_HOME=/opt/bgutil-ytdlp-pot-provider/server

# Install system dependencies for media processing
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     ffmpeg \
     git \
     curl \
     gnupg \
     ca-certificates \
  && mkdir -p /etc/apt/keyrings \
  && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
     | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
  && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
     > /etc/apt/sources.list.d/nodesource.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     nodejs \
  && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /bin/bash appuser

COPY requirements.txt requirements.txt
RUN python -m pip install --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt

# Install Playwright (for browser automation, Chromium not needed for YouTube downloads)
RUN pip install --no-cache-dir playwright

ARG BGUTIL_POT_PROVIDER_REF=1.3.1
RUN git clone --depth 1 --branch ${BGUTIL_POT_PROVIDER_REF} \
     https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
  && cd /opt/bgutil-ytdlp-pot-provider/server \
  && npm ci \
  && npx tsc

COPY frontend/package.json frontend/package.json
COPY frontend/tsconfig.json frontend/tsconfig.json
COPY frontend/tsconfig.app.json frontend/tsconfig.app.json
COPY frontend/tsconfig.node.json frontend/tsconfig.node.json
COPY frontend/vite.config.ts frontend/vite.config.ts
COPY frontend/index.html frontend/index.html
COPY frontend/src frontend/src
RUN cd frontend && npm install

# Optional local Whisper fallback (disabled by default to keep deployment lightweight)
ARG INSTALL_LOCAL_WHISPER=false
COPY requirements-local.txt requirements-local.txt
RUN if [ "$INSTALL_LOCAL_WHISPER" = "true" ]; then \
      pip install --no-cache-dir -r requirements-local.txt; \
    fi

COPY . .
RUN chown -R appuser:appuser /app
USER appuser

RUN chmod +x /app/start.sh

EXPOSE 8000
CMD ["sh", "/app/start.sh"]
