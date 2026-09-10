FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RECORDINGS_DIR=/app/evals/recordings

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY evals/recordings ./evals/recordings

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"

CMD ["uvicorn", "validator.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
