# Notification service - sent log. Build from repo root:
#   docker build -f services/notification/Dockerfile -t <user>/blast-radius-notification:1.0.0 .

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY services/notification/ services/notification/

ARG SERVICE_VERSION=1.0.0
ENV SERVICE_VERSION=${SERVICE_VERSION}

LABEL org.opencontainers.image.title="blast-radius-notification" \
      org.opencontainers.image.description="Notification service for the blast radius demo" \
      org.opencontainers.image.version="${SERVICE_VERSION}"

EXPOSE 8003

CMD ["python", "-m", "uvicorn", "services.notification.main:app", "--host", "0.0.0.0", "--port", "8003"]
