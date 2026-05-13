FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# System deps for Playwright's bundled Chromium (PlaywrightLocalBackend fallback)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl tini \
        fonts-liberation fonts-noto-color-emoji fonts-noto-cjk \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libx11-xcb1 libxss1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml backend/README.md ./
COPY backend/src ./src
RUN pip install --upgrade pip && \
    pip install -e . && \
    python -m playwright install chromium

RUN mkdir -p /app/output && \
    useradd -ms /bin/bash -u 10001 app && \
    chown -R app:app /app /ms-playwright
USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=4 --start-period=20s \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "fb_ads_scraper.api:app", "--host", "0.0.0.0", "--port", "8000"]
