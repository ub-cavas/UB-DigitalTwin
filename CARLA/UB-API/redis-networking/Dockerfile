FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libasound2 \
    libjpeg-turbo8 \
    libomp5 \
    libpng16-16 \
    libsdl2-2.0-0 \
    libtiff5 \
    libx11-6 \
    libxcursor1 \
    libxext6 \
    libxi6 \
    libxinerama1 \
    libxrandr2 \
    libxrender1 \
    libxxf86vm1 \
    python3 \
    python3-pip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ub-redis-networking

# Ubuntu 22.04 ships setuptools 59, which predates PEP 621 and silently builds
# pyproject.toml projects as "UNKNOWN" with no modules. Upgrade before any
# local install.
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Build context is CARLA/UB-API so that the shared telemetry package is
# reachable alongside this role's own sources.
COPY redis-networking/requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Shared wire protocol and transport, used by every role in this image.
COPY ub-telemetry/ /opt/ub-telemetry/
RUN python3 -m pip install --no-cache-dir /opt/ub-telemetry

COPY redis-networking/ .

ENV UB_REDIS_HOST=127.0.0.1 \
    UB_REDIS_PORT=6390 \
    UB_REDIS_PASSWORD=password \
    UB_REDIS_CHANNEL=carla:telemetry \
    UB_CARLA_HOST=127.0.0.1 \
    UB_CARLA_PORT=2000 \
    UB_REDIS_ROLE=none

ENTRYPOINT ["/bin/bash", "/opt/ub-redis-networking/sidecar-entrypoint.sh"]
