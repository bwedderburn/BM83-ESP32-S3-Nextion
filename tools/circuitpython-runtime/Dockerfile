# Supported host for cryptography 50: Intel macOS wheels were removed in 49.
# Resolve the official Python tag once, then keep the immutable base digest.
FROM --platform=linux/amd64 python@sha256:84fa927127b46670e768371d1ad1be271d57ba93a6fbb3479045c7c6c452432f

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 \
    IDF_TOOLS_PATH=/opt/idf-tools IDF_PYTHON_ENV_PATH=/opt/idf-venv \
    LC_ALL=C.UTF-8 LANG=C.UTF-8 TZ=UTC PYTHONHASHSEED=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential xz-utils unzip pkg-config libffi-dev libssl-dev \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/host-venv && \
    /opt/host-venv/bin/python -m pip install pip==26.2.2 cmake==3.30.9 ninja==1.13.2

COPY requirements-build.txt espidf.constraints.v6.0.txt bonds8-cccd24.patch source-pins.json /opt/recipe/

RUN git init /opt/circuitpython && \
    git -C /opt/circuitpython remote add origin https://github.com/adafruit/circuitpython.git && \
    git -C /opt/circuitpython fetch --depth 1 origin refs/tags/10.3.1:refs/tags/10.3.1 && \
    git -C /opt/circuitpython checkout --detach c9dee12beed76e4ffa11d2d6d99ff104fc976c3a && \
    cd /opt/circuitpython && python tools/ci_fetch_deps.py espressif_esp32s3_devkitc_1_n8r8 && \
    git -C ports/espressif/esp-idf submodule update --init --recursive --depth 1 && \
    test "$(git -C ports/espressif/esp-idf rev-parse HEAD)" = 2b900d1222cfce5dfa340ed99375af69ec1ee192 && \
    test "$(git -C ports/espressif/esp-idf/components/bt/host/nimble/nimble rev-parse HEAD)" = 7075927f97c648af650a288e94a8c80dd7f00c27 && \
    git apply --check /opt/recipe/bonds8-cccd24.patch && git apply /opt/recipe/bonds8-cccd24.patch

# IDF checks OpenOCD's version during install; this is a shared-library
# dependency only. Containers receive no USB devices or privileged access.
RUN apt-get update && apt-get install -y --no-install-recommends libusb-1.0-0 && \
    rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/opt/idf-tools/dist,id=bm83-cp1031-tool-downloads \
    /opt/host-venv/bin/python -u /opt/circuitpython/ports/espressif/esp-idf/tools/idf_tools.py install --targets esp32s3 && \
    python -m venv /opt/idf-venv && \
    /opt/idf-venv/bin/python -m pip install \
        --constraint /opt/recipe/espidf.constraints.v6.0.txt \
        --requirement /opt/recipe/requirements-build.txt && \
    cp /opt/recipe/espidf.constraints.v6.0.txt /opt/idf-tools/espidf.constraints.v6.0.txt && \
    printf '6.0' > /opt/idf-venv/idf_version.txt && \
    /opt/idf-venv/bin/python -m pip check

COPY build-runtime.sh record-build.py verify_host_tools.py reproducible-web-assets.patch hashlib-close.patch host-policy.patch /opt/recipe/
# Python 3.11's gzip default embeds wall-clock time in the web assets.
# Fix the generator input, never normalize or rewrite a completed binary.
RUN cd /opt/circuitpython && \
    git apply --check /opt/recipe/reproducible-web-assets.patch && \
    git apply /opt/recipe/reproducible-web-assets.patch && \
    git apply --check /opt/recipe/hashlib-close.patch && \
    git apply /opt/recipe/hashlib-close.patch && \
    git apply --check /opt/recipe/host-policy.patch && \
    git apply /opt/recipe/host-policy.patch && \
    git add --intent-to-add -- \
      ports/espressif/common-hal/_bleio/HostPolicy.c \
      ports/espressif/common-hal/_bleio/HostPolicy.h \
      ports/espressif/common-hal/_bleio/HostPolicyCore.c \
      ports/espressif/common-hal/_bleio/HostPolicyCore.h
WORKDIR /opt/circuitpython
ENTRYPOINT ["/bin/bash", "/opt/recipe/build-runtime.sh"]
