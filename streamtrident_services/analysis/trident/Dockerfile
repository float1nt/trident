# CUDA 12.8 + PyTorch 2.7+ required for RTX 5090 (Blackwell sm_120).
FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime AS cuda

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple

COPY requirements.txt .
RUN set -eux; \
    grep -v '^torch' requirements.txt | grep -v '^#' | grep -v '^[[:space:]]*$' | \
      xargs pip install --no-cache-dir -i "${PIP_INDEX_URL}"

RUN python -c "import torch; print('PyTorch', torch.__version__); print('CUDA built', torch.version.cuda); print('CUDA available', torch.cuda.is_available())"

COPY app ./app
COPY config ./config
COPY migrations ./migrations

RUN mkdir -p /var/lib/trident/models

CMD ["python", "-m", "app.worker", "--config", "config/trident.yaml"]


FROM python:3.11-slim AS cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG APT_MIRROR=deb.debian.org

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends libgomp1; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN mkdir -p /tmp/torch_wheels
COPY wheelhouse/ /tmp/torch_wheels/

RUN set -eux; \
    if ls /tmp/torch_wheels/torch-*cpu*.whl >/dev/null 2>&1; then \
      pip install --no-cache-dir /tmp/torch_wheels/torch-*cpu*.whl; \
    else \
      pip install --no-cache-dir torch -i "${PIP_INDEX_URL}"; \
    fi; \
    rm -rf /tmp/torch_wheels

RUN set -eux; \
    grep -v '^torch' requirements.txt | grep -v '^#' | grep -v '^[[:space:]]*$' | \
      xargs pip install --no-cache-dir -i "${PIP_INDEX_URL}"

RUN python -c "import torch; print('PyTorch', torch.__version__); print('CUDA available', torch.cuda.is_available())"

COPY app ./app
COPY config ./config
COPY migrations ./migrations

RUN mkdir -p /var/lib/trident/models

CMD ["python", "-m", "app.worker", "--config", "config/trident.yaml"]
