# Base image pinned by digest (the tag is on the FROM line); Dependabot proposes updates.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir "uvicorn==0.54.0" . \
    && useradd -u 1000 -m app && mkdir /data && chown app /data
USER app
ENV DATA_DIR=/data PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8765\")}/health')"
CMD ["python", "-m", "bring_mcp.server"]
