#!/usr/bin/env bash
# 移除失效的 docker.nju.edu.cn 镜像源（需 sudo）
set -euo pipefail

DAEMON_JSON="/etc/docker/daemon.json"
BACKUP="${DAEMON_JSON}.bak.$(date +%Y%m%d%H%M%S)"

if [[ ! -f "$DAEMON_JSON" ]]; then
  echo "未找到 $DAEMON_JSON"
  exit 1
fi

cp "$DAEMON_JSON" "$BACKUP"
python3 <<'PY'
import json
from pathlib import Path

path = Path("/etc/docker/daemon.json")
cfg = json.loads(path.read_text())
mirrors = [
    m for m in cfg.get("registry-mirrors", [])
    if "docker.nju.edu.cn" not in m
]
cfg["registry-mirrors"] = mirrors
path.write_text(json.dumps(cfg, indent=4) + "\n")
print("已更新 registry-mirrors:", mirrors)
PY

systemctl restart docker
echo "Docker 已重启。备份: $BACKUP"
