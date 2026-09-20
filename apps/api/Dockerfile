# Production API + worker image. Same image, different command per service.
# Build context is the repository root:
#   docker build -f apps/api/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# System tools required by PDF export QA and Chinese rendering:
#   poppler-utils -> pdfinfo / pdftotext / pdffonts
#   fonts-noto-cjk -> embedded CJK glyphs
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        fonts-noto-cjk \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Preserve the repository layout so app.config.ROOT resolves as on the host.
WORKDIR /srv/ai-job-coach/apps/api

COPY apps/api/pyproject.toml ./pyproject.toml
COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini
COPY scripts/prod_preflight.py ./scripts/prod_preflight.py

RUN pip install --no-cache-dir -e '.[pdf]'

# Chromium for headless PDF printing, with its shared-library dependencies.
RUN playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

RUN groupadd --system app && useradd --system --gid app --home /home/app --create-home app \
    && chown -R app:app /srv/ai-job-coach

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
