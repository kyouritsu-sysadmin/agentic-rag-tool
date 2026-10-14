FROM ghcr.io/astral-sh/uv:0.11.14 AS uv
FROM python:3.12.13-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src
COPY backend/alembic.ini ./backend/
COPY backend/migrations ./backend/migrations
ARG INSTALL_OCR=false
RUN if [ "$INSTALL_OCR" = "true" ]; then uv sync --frozen --no-dev --extra models --extra ocr; else uv sync --frozen --no-dev --extra models; fi
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/backend
RUN useradd --uid 10001 --create-home rag && mkdir -p /sources /home/rag/.cache && chown -R rag:rag /sources /home/rag/.cache && chown rag:rag /app
USER rag
EXPOSE 8000
CMD ["uvicorn", "kyoritsu_backend.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
