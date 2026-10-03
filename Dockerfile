FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

CMD ["python", "-m", "pjn_scw.cron"]
