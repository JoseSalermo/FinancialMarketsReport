FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV FINANCIAL_MARKET_REPORT_HOME=/app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY config ./config
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/reports /app/logs /run/secrets \
    && chown -R appuser:appuser /app /run/secrets

USER appuser

EXPOSE 8080

CMD ["financial-market-report", "serve", "--host", "0.0.0.0", "--port", "8080"]
