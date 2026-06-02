FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INDUSTRIAL_GATEWAY_HOST=0.0.0.0 \
    INDUSTRIAL_GATEWAY_PORT=50137 \
    INDUSTRIAL_GATEWAY_STORE=/opt/iot_gathering/gateway.sqlite3 \
    INDUSTRIAL_GATEWAY_LOG_ROOT=/opt/iot_gathering/industrial_gateway_log

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        unixodbc \
        unixodbc-dev \
        libpq5 \
        libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /opt/iot_gathering/industrial_gateway_log

EXPOSE 50137

CMD ["industrial-gateway-web"]
