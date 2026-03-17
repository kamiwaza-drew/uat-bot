FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN pip install --no-cache-dir uv && \
    useradd -m -u 10001 -s /bin/bash uat

COPY pyproject.toml README.md /app/
COPY uat_bot /app/uat_bot

RUN uv pip install --system .

RUN mkdir -p /data/runs /app/uat_bot/scenarios/custom && chown -R uat:uat /app /data

USER uat
EXPOSE 18090

CMD ["python", "-m", "uat_bot"]
