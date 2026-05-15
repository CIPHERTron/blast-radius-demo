# PIPA metrics generator. Build from the metrics-generator/ folder:
#
#   docker build -f metrics-generator/Dockerfile \
#     -t <user>/blast-radius-metrics-gen:1.0.0 metrics-generator/

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . ./

ENV PUSHGATEWAY_URL=http://8.229.139.162:9091 \
    PUSH_INTERVAL_SECONDS=5 \
    JOB_NAME=blast-radius-demo \
    INSTANCE=sim-0 \
    PORT=8090

EXPOSE 8090

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
