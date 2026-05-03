FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml /app/
RUN pip install --no-cache-dir .

COPY src /app/src

CMD ["python", "-m", "translator_service.bot"]

