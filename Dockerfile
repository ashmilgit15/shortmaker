FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# Install system dependencies for media processing
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     ffmpeg \
     git \
     nodejs \
     npm \
     ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /bin/bash appuser

COPY requirements.txt requirements.txt
RUN python -m pip install --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt

COPY frontend/package.json frontend/package.json
COPY frontend/package-lock.json frontend/package-lock.json
COPY frontend/tsconfig.json frontend/tsconfig.json
COPY frontend/tsconfig.app.json frontend/tsconfig.app.json
COPY frontend/tsconfig.node.json frontend/tsconfig.node.json
COPY frontend/vite.config.ts frontend/vite.config.ts
COPY frontend/index.html frontend/index.html
COPY frontend/src frontend/src
RUN cd frontend && npm ci

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
