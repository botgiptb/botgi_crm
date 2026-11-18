FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt /app/
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . /app/

RUN python manage.py collectstatic --noinput || true

EXPOSE 8000
