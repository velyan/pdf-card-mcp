FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m pip install --upgrade --no-cache-dir pip

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

ENTRYPOINT ["pdf-card-mcp-server"]
