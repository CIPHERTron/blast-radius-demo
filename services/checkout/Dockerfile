# Checkout service - the main orchestrator. Build context is the repo
# root so we can pick up requirements.txt, the service code, and the
# dashboard/ folder which checkout serves as static files.
#
#   docker build -f services/checkout/Dockerfile -t <user>/blast-radius-checkout:1.0.0 .
#
# To bake the broken build:
#   docker build -f services/checkout/Dockerfile \
#     --build-arg SERVICE_VERSION=1.0.1-broken --build-arg BROKEN=1 \
#     -t <user>/blast-radius-checkout:1.0.1-broken .

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY services/checkout/ services/checkout/
COPY dashboard/ dashboard/

ARG SERVICE_VERSION=1.0.0
ARG BROKEN=0

ENV SERVICE_VERSION=${SERVICE_VERSION} \
    BROKEN=${BROKEN} \
    INVENTORY_URL=http://inventory:8001 \
    PAYMENT_URL=http://payment:8002 \
    NOTIFICATION_URL=http://notification:8003

LABEL org.opencontainers.image.title="blast-radius-checkout" \
      org.opencontainers.image.description="Checkout orchestrator for the blast radius demo" \
      org.opencontainers.image.version="${SERVICE_VERSION}"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "services.checkout.main:app", "--host", "0.0.0.0", "--port", "8000"]
