FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN useradd -m -u 1000 -s /bin/bash carla

# Runtime dependencies for packaged CARLA/Unreal Linux builds with X11,
# OpenGL/EGL, Vulkan, audio stubs, and NVIDIA container passthrough.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libasound2 \
    libegl1 \
    libgl1 \
    libglu1-mesa \
    libglvnd0 \
    libglx0 \
    libjpeg-turbo8 \
    libnss3 \
    libomp5 \
    libpng16-16 \
    libsdl2-2.0-0 \
    libtiff5 \
    libvulkan1 \
    libx11-6 \
    libxcomposite1 \
    libxcursor1 \
    libxext6 \
    libxi6 \
    libxinerama1 \
    libxkbcommon0 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    mesa-utils \
    python3 \
    python3-pip \
    vulkan-tools \
    xdg-user-dirs \
 && rm -rf /var/lib/apt/lists/*

ENV OMP_PROC_BIND=FALSE \
    OMP_NUM_THREADS=48 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=all \
    __GLX_VENDOR_LIBRARY_NAME=nvidia \
    LIBGL_ALWAYS_INDIRECT=0

WORKDIR /carla
USER carla

# Mount a packaged CARLA build, for example:
# docker run ... -v "$PWD/CARLA/Builds/v1.0.0:/carla:rw" ub-carla
ENTRYPOINT ["/bin/bash", "/carla/CarlaUE4.sh"]
CMD ["-prefernvidia", "-nosound"]
