FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN pip install --no-cache-dir uv && \
    useradd -m -u 10001 -s /bin/bash stress

COPY pyproject.toml README.md /app/
COPY stress_tester /app/stress_tester

RUN uv pip install --system .

RUN mkdir -p /data/runs /app/stress_tester/scenarios/custom && chown -R stress:stress /app /data

USER stress
EXPOSE 18090

CMD ["python", "-m", "stress_tester"]
