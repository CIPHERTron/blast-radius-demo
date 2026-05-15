# Inventory service - tracks stock and reservations. Build from repo root:
#   docker build -f services/inventory/Dockerfile -t <user>/blast-radius-inventory:1.0.0 .

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY services/inventory/ services/inventory/

ARG SERVICE_VERSION=1.0.0
ENV SERVICE_VERSION=${SERVICE_VERSION}

LABEL org.opencontainers.image.title="blast-radius-inventory" \
      org.opencontainers.image.description="Inventory service for the blast radius demo" \
      org.opencontainers.image.version="${SERVICE_VERSION}"

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "services.inventory.main:app", "--host", "0.0.0.0", "--port", "8001"]
