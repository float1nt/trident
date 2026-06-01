#!/usr/bin/env bash
# Pre-download wheels for the CPU Docker target (optional offline builds).
# CUDA target uses pytorch/pytorch base image and does not need wheelhouse.
# Run from streamtrident_services/analysis/trident:
#   bash scripts/download-gpu-deps.sh
set -euo pipefail

cd "$(dirname "$0")/.."
WHEELHOUSE="${WHEELHOUSE:-./wheelhouse}"
PIP_INDEX="${PIP_INDEX:-https://pypi.org/simple}"
PYTHON_TAG="${PYTHON_TAG:-311}"
PIP_TIMEOUT="${PIP_TIMEOUT:-600}"

export PIP_CONFIG_FILE=/dev/null

PYTORCH_INDEXES=(
  "${PYTORCH_INDEX:-}"
  "https://mirror.sjtu.edu.cn/pytorch-wheels/cu124/"
  "https://mirrors.nju.edu.cn/pytorch/wheels/cu124/"
  "https://mirrors.huaweicloud.com/pytorch-wheels/cu124/"
  "https://download.pytorch.org/whl/cu124"
  "https://download.pytorch.org/whl/cu121"
)

mkdir -p "${WHEELHOUSE}"

download_torch() {
  local index="$1"
  echo "==> Trying torch from ${index}"
  pip download torch \
    -d "${WHEELHOUSE}" \
    --index-url "${index}" \
    --python-version "${PYTHON_TAG}" \
    --only-binary=:all: \
    --timeout "${PIP_TIMEOUT}"
}

echo "==> Downloading torch (CUDA) into ${WHEELHOUSE}"
TORCH_OK=0
for index in "${PYTORCH_INDEXES[@]}"; do
  [ -z "${index}" ] && continue
  if download_torch "${index}"; then
    TORCH_OK=1
    break
  fi
  echo "WARN: failed from ${index}" >&2
done

if [ "${TORCH_OK}" -ne 1 ]; then
  echo "ERROR: could not download torch from any configured index" >&2
  exit 1
fi

REQ_NO_TORCH="$(mktemp)"
grep -v '^torch' requirements.txt | grep -v '^#' | grep -v '^[[:space:]]*$' > "${REQ_NO_TORCH}"

echo "==> Downloading other requirements"
pip download -r "${REQ_NO_TORCH}" \
  -d "${WHEELHOUSE}" \
  -i "${PIP_INDEX}" \
  --python-version "${PYTHON_TAG}" \
  --timeout "${PIP_TIMEOUT}"

rm -f "${REQ_NO_TORCH}"

echo "==> Done. Wheels:"
ls -lh "${WHEELHOUSE}"/torch-*.whl 2>/dev/null || ls -lh "${WHEELHOUSE}"
