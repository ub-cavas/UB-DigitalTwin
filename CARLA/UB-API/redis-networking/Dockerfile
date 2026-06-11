FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libjpeg-turbo8 \
    libomp5 \
    libpng16-16 \
    libtiff5 \
    python3 \
    python3-pip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ub-redis-networking

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

ENV UB_REDIS_HOST=127.0.0.1 \
    UB_REDIS_PORT=6390 \
    UB_REDIS_PASSWORD=password \
    UB_REDIS_CHANNEL=carla:telemetry \
    UB_CARLA_HOST=127.0.0.1 \
    UB_CARLA_PORT=2000 \
    UB_REDIS_ROLE=none

ENTRYPOINT ["/bin/bash", "/opt/ub-redis-networking/sidecar-entrypoint.sh"]
