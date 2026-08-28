FROM python:3.12-slim

WORKDIR /app

# Non-root user (§CODE STANDARDS)
RUN useradd -m -r appuser && chown -R appuser:appuser /app

# Dependencies
COPY pyproject.toml README* ./
RUN pip install --no-cache-dir .

# Application code
COPY app/ main.py ./

ENV PYTHONUNBUFFERED=1
ENV HEALTH_CHECK_PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:${HEALTH_CHECK_PORT:-8080}/health')" || exit 1

EXPOSE 8080

USER appuser

CMD ["python", "main.py"]
