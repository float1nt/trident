from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp/mplconfig-trident").resolve()))

from trident_demo.pipeline.runner import run_pipeline


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "trident_demo/stress/configs/e2e.yaml"
DEFAULT_REPLAY_IMAGE = "trident-tcpreplay:local"
REPLAY_DOCKERFILE = REPO_ROOT / "trident_demo/stress/docker/tcpreplay.Dockerfile"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_id_now() -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_e2e_stress"


def resolve_path(raw: str, *, base: Path = REPO_ROOT) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else (base / path).resolve()


def run_cmd(
    cmd: List[str],
    *,
    cwd: Path = REPO_ROOT,
    env: Optional[Dict[str, str]] = None,
    log_path: Optional[Path] = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    started = time.perf_counter()
    if log_path is not None and not capture:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"$ {' '.join(cmd)}\n")
            f.flush()
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=merged_env,
                text=True,
                stdout=f,
                stderr=subprocess.STDOUT,
                check=False,
            )
            f.write(f"exit_code={proc.returncode} elapsed_seconds={time.perf_counter() - started:.6f}\n\n")
    else:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=merged_env,
            text=True,
            capture_output=True,
            check=False,
        )
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"$ {' '.join(cmd)}\n")
                if proc.stdout:
                    f.write(proc.stdout)
                    if not proc.stdout.endswith("\n"):
                        f.write("\n")
                if proc.stderr:
                    f.write(proc.stderr)
                    if not proc.stderr.endswith("\n"):
                        f.write("\n")
                f.write(f"exit_code={proc.returncode} elapsed_seconds={time.perf_counter() - started:.6f}\n\n")
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


@dataclass
class StressConfig:
    raw: Dict[str, Any]
    run_id: str
    output_root: Path
    run_dir: Path
    redis_url: str
    redis_stream: str
    redis_max_messages: int
    redis_idle_timeout: float
    redis_clear_stream: bool
    redis_stream_maxlen: int
    compose_dir: Path
    suricata_image: str
    suricata_service: str
    suricata_container: str
    suricata_iface: str
    suricata_start: bool
    suricata_force_recreate: bool
    suricata_stop_after_run: bool
    pcap: Path
    replay_iface: str
    replay_mbps: float
    replay_pps: float
    replay_multiplier: float
    replay_loop: int
    replay_mtu_trunc: str
    replay_use_docker: bool
    replay_docker_image: str
    replay_min_replay_seconds: float
    replay_min_stream_len: int
    replay_max_rounds: int
    wait_after_replay_seconds: float
    sample_interval_seconds: float
    baseline_seconds: float
    trident_config: Path
    trident_max_rows: int
    trident_profile: str
    trident_output_dir: Path
    trident_timeout_seconds: int
    perf_mode: bool
    perf_window_size: int
    perf_disable_new_learner: bool
    suricata_settle_quiet_seconds: float
    suricata_settle_growth_epsilon_fps: float


def load_config(path: Path) -> StressConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Stress config must be a mapping: {path}")
    runtime = payload.get("runtime", {}) if isinstance(payload.get("runtime"), dict) else {}
    redis = payload.get("redis", {}) if isinstance(payload.get("redis"), dict) else {}
    suricata = payload.get("suricata", {}) if isinstance(payload.get("suricata"), dict) else {}
    replay = payload.get("tcpreplay", {}) if isinstance(payload.get("tcpreplay"), dict) else {}
    trident = payload.get("trident", {}) if isinstance(payload.get("trident"), dict) else {}

    run_id = str(runtime.get("run_id") or run_id_now())
    output_root = resolve_path(str(runtime.get("output_root", "trident_demo/testing/outputs/stress")))
    run_dir = (output_root / run_id).resolve()
    stream = str(redis.get("stream") or f"suricata:cic_flow:{run_id}")
    return StressConfig(
        raw=payload,
        run_id=run_id,
        output_root=output_root,
        run_dir=run_dir,
        redis_url=str(redis.get("url", "redis://127.0.0.1:6379/0")),
        redis_stream=stream,
        redis_max_messages=int(redis.get("max_messages", trident.get("max_rows", 100000)) or 0),
        redis_idle_timeout=float(redis.get("idle_timeout_seconds", 180.0) or 180.0),
        redis_clear_stream=bool(redis.get("clear_stream", True)),
        redis_stream_maxlen=int(redis.get("stream_maxlen", 1000000) or 1000000),
        compose_dir=resolve_path(str(suricata.get("compose_dir", "suricata-cic-redis-live"))),
        suricata_image=str(suricata.get("image", "suricata-cic-live:local")),
        suricata_service=str(suricata.get("service", "suricata-cic")),
        suricata_container=str(suricata.get("container", "suricata-cic-live")),
        suricata_iface=str(suricata.get("iface", replay.get("iface", "ens33"))),
        suricata_start=bool(suricata.get("start", True)),
        suricata_force_recreate=bool(suricata.get("force_recreate", True)),
        suricata_stop_after_run=bool(suricata.get("stop_after_run", False)),
        pcap=resolve_path(str(replay.get("pcap", ""))) if replay.get("pcap") else Path(""),
        replay_iface=str(replay.get("iface", suricata.get("iface", "ens33"))),
        replay_mbps=float(replay.get("mbps", 0.0) or 0.0),
        replay_pps=float(replay.get("pps", 0.0) or 0.0),
        replay_multiplier=float(replay.get("multiplier", 0.0) or 0.0),
        replay_loop=max(1, int(replay.get("loop", 1) or 1)),
        replay_mtu_trunc=str(replay.get("mtu_trunc", "auto")).strip().lower(),
        replay_use_docker=bool(replay.get("use_docker", False)),
        replay_docker_image=str(replay.get("docker_image", DEFAULT_REPLAY_IMAGE)),
        replay_min_replay_seconds=float(replay.get("min_replay_seconds", 60.0) or 0.0),
        replay_min_stream_len=int(replay.get("min_stream_len", 0) or 0),
        replay_max_rounds=max(1, int(replay.get("max_rounds", 1000) or 1000)),
        wait_after_replay_seconds=float(runtime.get("wait_after_replay_seconds", 30.0) or 0.0),
        sample_interval_seconds=float(runtime.get("sample_interval_seconds", 1.0) or 1.0),
        baseline_seconds=float(runtime.get("baseline_seconds", 3.0) or 0.0),
        trident_config=resolve_path(str(trident.get("config", "trident_demo/configs/benchmark.yaml"))),
        trident_max_rows=int(trident.get("max_rows", redis.get("max_messages", 100000)) or 0),
        trident_profile=str(trident.get("profile", "benchmark")),
        trident_output_dir=(run_dir / "trident").resolve(),
        trident_timeout_seconds=int(trident.get("timeout_seconds", 86400) or 86400),
        perf_mode=bool(runtime.get("perf_mode", trident.get("perf_mode", False))),
        perf_window_size=int(runtime.get("perf_window_size", trident.get("perf_window_size", 20000)) or 0),
        perf_disable_new_learner=bool(
            runtime.get("perf_disable_new_learner", trident.get("perf_disable_new_learner", False))
        ),
        suricata_settle_quiet_seconds=float(runtime.get("suricata_settle_quiet_seconds", 3.0) or 3.0),
        suricata_settle_growth_epsilon_fps=float(runtime.get("suricata_settle_growth_epsilon_fps", 10.0) or 10.0),
    )


class PeriodicSampler:
    def __init__(self, interval: float) -> None:
        self.interval = max(0.2, float(interval))
        self.stop_event = threading.Event()
        self.threads: List[threading.Thread] = []

    def add(self, target: Any) -> None:
        self.threads.append(threading.Thread(target=target, daemon=True))

    def start(self) -> None:
        for thread in self.threads:
            thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=2.0)


def sample_redis(cfg: StressConfig, sampler: PeriodicSampler) -> None:
    rows: List[Dict[str, Any]] = []
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(cfg.redis_url, decode_responses=True)
        while not sampler.stop_event.wait(sampler.interval):
            row: Dict[str, Any] = {"timestamp": utc_now()}
            try:
                info = client.info()
                row.update(
                    {
                        "xlen": int(client.xlen(cfg.redis_stream)),
                        "used_memory": int(info.get("used_memory", 0)),
                        "used_memory_peak": int(info.get("used_memory_peak", 0)),
                        "used_memory_rss": int(info.get("used_memory_rss", 0)),
                        "instantaneous_ops_per_sec": int(info.get("instantaneous_ops_per_sec", 0)),
                        "instantaneous_input_kbps": float(info.get("instantaneous_input_kbps", 0.0)),
                        "instantaneous_output_kbps": float(info.get("instantaneous_output_kbps", 0.0)),
                    }
                )
            except Exception as exc:
                row["error"] = str(exc)
            rows.append(row)
    except ImportError:
        rows.append({"timestamp": utc_now(), "error": "python redis package is not installed"})
    numeric = [r for r in rows if "error" not in r]
    summary = {
        "sample_count": len(numeric),
        "xlen_max": max([int(r.get("xlen", 0)) for r in numeric] or [0]),
        "xlen_last": int(numeric[-1].get("xlen", 0)) if numeric else 0,
        "used_memory_peak_max": max([int(r.get("used_memory_peak", 0)) for r in numeric] or [0]),
    }
    write_json(cfg.run_dir / "redis_metrics.json", {"stream": cfg.redis_stream, "samples": rows, "summary": summary})


def sample_docker(cfg: StressConfig, sampler: PeriodicSampler) -> None:
    rows: List[Dict[str, Any]] = []
    if not shutil.which("docker"):
        write_json(cfg.run_dir / "docker_metrics.json", {"error": "docker not found", "samples": []})
        return
    names = ["cic-redis", cfg.suricata_container]
    while not sampler.stop_event.wait(sampler.interval):
        for name in names:
            proc = run_cmd(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", name],
                check=False,
                capture=True,
            )
            row: Dict[str, Any] = {"timestamp": utc_now(), "container": name, "exit_code": proc.returncode}
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    row.update(json.loads(proc.stdout.strip().splitlines()[0]))
                except json.JSONDecodeError:
                    row["raw"] = proc.stdout.strip()
            elif proc.stderr.strip():
                row["error"] = proc.stderr.strip()
            rows.append(row)
    write_json(cfg.run_dir / "docker_metrics.json", {"samples": rows})


def docker_env(cfg: StressConfig) -> Dict[str, str]:
    return {
        "IFACE": cfg.suricata_iface,
        "REDIS_STREAM": cfg.redis_stream,
        "REDIS_STREAM_MAXLEN": str(cfg.redis_stream_maxlen),
    }


def preflight(cfg: StressConfig) -> None:
    errors: List[str] = []
    if not shutil.which("docker"):
        errors.append("docker not found in PATH")
    if not cfg.replay_use_docker and not shutil.which("tcpreplay"):
        errors.append("tcpreplay not found in PATH")
    if not cfg.compose_dir.joinpath("docker-compose.yml").is_file():
        errors.append(f"docker-compose.yml not found: {cfg.compose_dir / 'docker-compose.yml'}")
    if not cfg.trident_config.is_file():
        errors.append(f"Trident config not found: {cfg.trident_config}")
    if not cfg.pcap.is_file():
        errors.append(f"pcap not found: {cfg.pcap}")
    if errors:
        raise RuntimeError("; ".join(errors))
    if cfg.replay_use_docker:
        ensure_replay_image(cfg)

    run_cmd(["docker", "image", "inspect", cfg.suricata_image], log_path=cfg.run_dir / "commands.log")
    ldd = run_cmd(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/bash",
            cfg.suricata_image,
            "-lc",
            "ldd /opt/suricata-cic/bin/suricata",
        ],
        log_path=cfg.run_dir / "preflight_ldd.log",
        capture=True,
    )
    if "not found" in (ldd.stdout + ldd.stderr):
        raise RuntimeError("Suricata image has missing shared libraries. See preflight_ldd.log.")


def redis_client(cfg: StressConfig) -> Any:
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python redis package is required") from exc
    return redis.Redis.from_url(cfg.redis_url, decode_responses=True)


def wait_for_redis(cfg: StressConfig, timeout: float = 45.0) -> None:
    client = redis_client(cfg)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            client.ping()
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Redis not reachable: {cfg.redis_url}")


def start_services(cfg: StressConfig) -> None:
    env = docker_env(cfg)
    run_cmd(["docker", "compose", "up", "-d", "redis"], cwd=cfg.compose_dir, env=env, log_path=cfg.run_dir / "commands.log")
    wait_for_redis(cfg)
    if cfg.redis_clear_stream:
        redis_client(cfg).delete(cfg.redis_stream)
    if cfg.suricata_start:
        cmd = ["docker", "compose", "up", "-d"]
        if cfg.suricata_force_recreate:
            cmd.append("--force-recreate")
        cmd.append(cfg.suricata_service)
        run_cmd(cmd, cwd=cfg.compose_dir, env=env, log_path=cfg.run_dir / "commands.log")
        time.sleep(2)
        inspect = run_cmd(
            ["docker", "inspect", "-f", "{{.State.Running}}", cfg.suricata_container],
            log_path=cfg.run_dir / "commands.log",
            capture=True,
            check=False,
        )
        if "true" not in inspect.stdout.strip().lower():
            logs = run_cmd(["docker", "logs", cfg.suricata_container], log_path=cfg.run_dir / "suricata_container_start.log", capture=True, check=False)
            raise RuntimeError(f"Suricata container is not running. See suricata_container_start.log: {logs.stderr.strip()}")


def stop_suricata_capture(cfg: StressConfig) -> None:
    run_cmd(
        ["docker", "stop", cfg.suricata_container],
        log_path=cfg.run_dir / "commands.log",
        check=False,
    )


def stop_services(cfg: StressConfig) -> None:
    if cfg.suricata_stop_after_run:
        run_cmd(["docker", "compose", "down"], cwd=cfg.compose_dir, log_path=cfg.run_dir / "commands.log", check=False)


def tcpreplay_supports_mtu_trunc() -> bool:
    proc = run_cmd(["tcpreplay", "--help"], capture=True, check=False)
    return "--mtu-trunc" in (proc.stdout + proc.stderr)


def replay_image_has_tcpreplay(image: str) -> bool:
    probe = run_cmd(
        ["docker", "run", "--rm", "--entrypoint", "/bin/sh", image, "-lc", "command -v tcpreplay"],
        capture=True,
        check=False,
    )
    return probe.returncode == 0 and bool((probe.stdout or "").strip())


def ensure_replay_image(cfg: StressConfig) -> None:
    inspect = run_cmd(
        ["docker", "image", "inspect", cfg.replay_docker_image],
        capture=True,
        check=False,
        log_path=cfg.run_dir / "commands.log",
    )
    needs_build = inspect.returncode != 0
    if not needs_build:
        needs_build = not replay_image_has_tcpreplay(cfg.replay_docker_image)
    if not needs_build:
        return
    if not REPLAY_DOCKERFILE.is_file():
        raise RuntimeError(f"Replay Dockerfile not found: {REPLAY_DOCKERFILE}")
    run_cmd(
        [
            "docker",
            "build",
            "-t",
            cfg.replay_docker_image,
            "-f",
            str(REPLAY_DOCKERFILE),
            str(REPO_ROOT),
        ],
        log_path=cfg.run_dir / "commands.log",
    )


def build_replay_cmd(cfg: StressConfig) -> List[str]:
    inner: List[str] = ["tcpreplay", "-i", cfg.replay_iface]
    if cfg.replay_mbps > 0:
        inner.extend(["--mbps", str(cfg.replay_mbps)])
    elif cfg.replay_pps > 0:
        inner.extend(["--pps", str(cfg.replay_pps)])
    elif cfg.replay_multiplier > 0:
        inner.extend(["--multiplier", str(cfg.replay_multiplier)])
    else:
        inner.append("--topspeed")
    if cfg.replay_loop > 1:
        inner.extend(["--loop", str(cfg.replay_loop)])
    inner.append("/pcap")

    if not cfg.replay_use_docker:
        inner[-1] = str(cfg.pcap)
        return inner

    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--cap-add=NET_RAW",
        "--cap-add=NET_ADMIN",
        "-v",
        f"{cfg.pcap}:/pcap:ro",
        cfg.replay_docker_image,
        *inner,
    ]


def run_replay_until_load(cfg: StressConfig) -> Dict[str, Any]:
    rounds = 0
    replay_seconds = 0.0
    started = time.monotonic()
    last_xlen = 0
    replay_cmd = build_replay_cmd(cfg)
    client = redis_client(cfg)
    target_seconds = max(0.0, float(cfg.replay_min_replay_seconds))
    target_stream_len = max(0, int(cfg.replay_min_stream_len))
    rounds_limit = max(1, int(cfg.replay_max_rounds))
    replay_log = cfg.run_dir / "replay.log"

    while rounds < rounds_limit:
        round_start = time.perf_counter()
        proc = run_cmd(replay_cmd, log_path=replay_log, capture=True, check=False)
        output_blob = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        if proc.returncode != 0:
            raise RuntimeError(f"tcpreplay failed (exit={proc.returncode})")
        replay_seconds += max(0.0, time.perf_counter() - round_start)
        rounds += 1
        try:
            last_xlen = int(client.xlen(cfg.redis_stream))
        except Exception:
            last_xlen = 0
        rate_mbps: Optional[float] = None
        for line in output_blob.splitlines():
            if "Rated:" in line and "Mbps" in line:
                parts = line.split("Rated:", 1)[-1].split(",")
                if len(parts) >= 2 and "Mbps" in parts[1]:
                    try:
                        rate_mbps = float(parts[1].replace("Mbps", "").strip())
                    except Exception:
                        rate_mbps = None
                break

        reached_seconds = target_seconds <= 0.0 or replay_seconds >= target_seconds
        reached_stream = target_stream_len <= 0 or last_xlen >= target_stream_len
        print(
            (
                "[ReplayProgress] "
                f"round={rounds}/{rounds_limit} "
                f"rated_mbps={rate_mbps if rate_mbps is not None else 'n/a'} "
                f"stream_len={last_xlen}/{target_stream_len} "
                f"replay_seconds={replay_seconds:.2f}/{target_seconds:.2f} "
                f"reached_seconds={reached_seconds} reached_stream={reached_stream}"
            ),
            flush=True,
        )
        if reached_seconds and reached_stream:
            break

    return {
        "rounds": int(rounds),
        "replay_seconds": float(round(replay_seconds, 4)),
        "elapsed_seconds_total": float(round(time.monotonic() - started, 4)),
        "stream_len_after_replay": int(last_xlen),
        "target_seconds": float(target_seconds),
        "target_stream_len": int(target_stream_len),
        "rounds_limit": int(rounds_limit),
        "stopped_due_to_round_limit": bool(rounds >= rounds_limit),
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not result == result:  # NaN
        return default
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_percent(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    raw = value.strip().replace("%", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_mem_mib(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    first = value.split("/", 1)[0].strip()
    if not first:
        return None
    parts = first.split()
    if len(parts) != 2:
        return None
    try:
        amount = float(parts[0])
    except ValueError:
        return None
    unit = parts[1].lower()
    factor = {
        "b": 1.0 / (1024**2),
        "kb": 1.0 / 1024.0,
        "kib": 1.0 / 1024.0,
        "mb": 1.0,
        "mib": 1.0,
        "gb": 1024.0,
        "gib": 1024.0,
        "tb": 1024.0 * 1024.0,
        "tib": 1024.0 * 1024.0,
    }.get(unit)
    if factor is None:
        return None
    return amount * factor


def _summarize_container_usage(samples: List[Dict[str, Any]], container: str) -> Dict[str, float]:
    picked = [row for row in samples if str(row.get("container") or row.get("Name")) == container]
    cpus = [v for v in (_parse_percent(row.get("CPUPerc")) for row in picked) if v is not None]
    mems = [v for v in (_parse_mem_mib(row.get("MemUsage")) for row in picked) if v is not None]
    return {
        "sample_count": float(len(picked)),
        "cpu_percent_avg": float(sum(cpus) / len(cpus)) if cpus else 0.0,
        "cpu_percent_max": float(max(cpus)) if cpus else 0.0,
        "mem_mib_max": float(max(mems)) if mems else 0.0,
    }


def wait_for_suricata_settle(cfg: StressConfig, client: Any) -> Dict[str, Any]:
    max_wait = max(0.0, float(cfg.wait_after_replay_seconds))
    quiet_seconds_needed = max(0.2, float(cfg.suricata_settle_quiet_seconds))
    growth_epsilon_fps = max(0.0, float(cfg.suricata_settle_growth_epsilon_fps))
    interval = max(0.2, min(1.0, float(cfg.sample_interval_seconds)))

    start = time.monotonic()
    quiet_for = 0.0
    reason = "max_wait_reached"
    samples: List[Dict[str, Any]] = []

    try:
        prev_xlen = int(client.xlen(cfg.redis_stream))
    except Exception:
        prev_xlen = 0
    start_xlen = prev_xlen

    while (time.monotonic() - start) < max_wait:
        time.sleep(interval)
        now = time.monotonic()
        try:
            current_xlen = int(client.xlen(cfg.redis_stream))
            error = ""
        except Exception as exc:
            current_xlen = prev_xlen
            error = str(exc)
        delta = current_xlen - prev_xlen
        growth_fps = float(delta) / interval
        elapsed = now - start
        samples.append(
            {
                "elapsed_seconds": round(elapsed, 4),
                "xlen": int(current_xlen),
                "delta": int(delta),
                "growth_fps": float(round(growth_fps, 4)),
                "error": error,
            }
        )
        if growth_fps <= growth_epsilon_fps:
            quiet_for += interval
        else:
            quiet_for = 0.0
        prev_xlen = current_xlen
        if quiet_for >= quiet_seconds_needed:
            reason = "steady_state_detected"
            break

    settle_seconds = time.monotonic() - start
    end_xlen = prev_xlen
    growth_values = [float(row.get("growth_fps", 0.0)) for row in samples if not row.get("error")]
    return {
        "max_wait_seconds": float(max_wait),
        "quiet_seconds_needed": float(quiet_seconds_needed),
        "growth_epsilon_fps": float(growth_epsilon_fps),
        "sample_interval_seconds": float(interval),
        "reason": reason,
        "settle_seconds": float(round(settle_seconds, 4)),
        "xlen_start": int(start_xlen),
        "xlen_end": int(end_xlen),
        "xlen_growth": int(max(0, end_xlen - start_xlen)),
        "growth_fps_avg": float(round(sum(growth_values) / len(growth_values), 4)) if growth_values else 0.0,
        "growth_fps_max": float(round(max(growth_values), 4)) if growth_values else 0.0,
        "samples": samples,
    }


def build_component_metrics(
    cfg: StressConfig,
    *,
    replay_summary: Dict[str, Any],
    settle_summary: Dict[str, Any],
    trident_benchmark: Dict[str, Any],
    redis_report: Dict[str, Any],
    docker_report: Dict[str, Any],
    xlen_before_replay: int,
    derived_timing: Dict[str, float],
) -> Dict[str, Any]:
    xlen_after_replay = _safe_int(replay_summary.get("stream_len_after_replay"), 0)
    xlen_after_settle = _safe_int(settle_summary.get("xlen_end"), xlen_after_replay)
    replay_seconds = _safe_float(replay_summary.get("replay_seconds"), 0.0)
    settle_seconds = _safe_float(settle_summary.get("settle_seconds"), 0.0)
    total_suricata_seconds = max(0.0, replay_seconds + settle_seconds)

    replay_flow_delta = max(0, xlen_after_replay - int(xlen_before_replay))
    tail_flow_delta = max(0, xlen_after_settle - xlen_after_replay)
    total_flow_delta = max(0, xlen_after_settle - int(xlen_before_replay))

    docker_samples = docker_report.get("samples")
    docker_rows = docker_samples if isinstance(docker_samples, list) else []
    suricata_usage = _summarize_container_usage(docker_rows, cfg.suricata_container)

    trident_throughput = trident_benchmark.get("throughput_flows_per_second")
    trident_throughput = trident_throughput if isinstance(trident_throughput, dict) else {}
    trident_resource = trident_benchmark.get("resource_usage")
    trident_resource = trident_resource if isinstance(trident_resource, dict) else {}
    trident_stages = trident_benchmark.get("stages_seconds")
    trident_stages = trident_stages if isinstance(trident_stages, dict) else {}
    trident_runtime_seconds = max(0.0, _safe_float(derived_timing.get("trident_thread_runtime_seconds"), 0.0))

    trident_stream_flows = _safe_float(trident_benchmark.get("stream_flow_count"), 0.0)
    trident_pipeline_flows = _safe_float(trident_benchmark.get("flow_count"), 0.0)
    trident_analysis_seconds = max(0.0, _safe_float(derived_timing.get("trident_analysis_total_seconds"), 0.0))
    trident_pipeline_seconds = max(0.0, _safe_float(trident_stages.get("pipeline_total"), 0.0))
    trident_experiment_seconds = max(0.0, _safe_float(trident_stages.get("pipeline_experiment"), 0.0))
    trident_stream_window_seconds = max(0.0, _safe_float(trident_stages.get("stream_window_total"), 0.0))
    trident_inference_seconds = max(0.0, _safe_float(trident_stages.get("stream_inference"), 0.0))
    trident_init_seconds = max(0.0, _safe_float(trident_stages.get("init_create_learner"), 0.0))
    trident_wait_seconds = max(
        0.0,
        trident_experiment_seconds - trident_stream_window_seconds - trident_init_seconds,
    )

    redis_summary = redis_report.get("summary")
    redis_summary = redis_summary if isinstance(redis_summary, dict) else {}

    return {
        "suricata": {
            "xlen_before_replay": int(xlen_before_replay),
            "xlen_after_replay": int(xlen_after_replay),
            "xlen_after_settle": int(xlen_after_settle),
            "flow_delta_replay": int(replay_flow_delta),
            "flow_delta_settle": int(tail_flow_delta),
            "flow_delta_total": int(total_flow_delta),
            "replay_seconds": float(round(replay_seconds, 4)),
            "settle_seconds": float(round(settle_seconds, 4)),
            "process_seconds_total": float(round(total_suricata_seconds, 4)),
            "flow_fps_replay_only": float(round(replay_flow_delta / replay_seconds, 4)) if replay_seconds > 0 else 0.0,
            "flow_fps_tail_only": float(round(tail_flow_delta / settle_seconds, 4)) if settle_seconds > 0 else 0.0,
            "flow_fps_total": float(round(total_flow_delta / total_suricata_seconds, 4)) if total_suricata_seconds > 0 else 0.0,
            "resource": suricata_usage,
        },
        "trident": {
            "analysis_seconds_total": float(round(trident_analysis_seconds, 4)),
            "pipeline_seconds_total": float(round(trident_pipeline_seconds, 4)),
            "runtime_seconds_total": float(round(trident_runtime_seconds, 4)),
            "experiment_seconds_total": float(round(trident_experiment_seconds, 4)),
            "stream_window_seconds_total": float(round(trident_stream_window_seconds, 4)),
            "inference_seconds_total": float(round(trident_inference_seconds, 4)),
            "init_seconds_total": float(round(trident_init_seconds, 4)),
            "wait_seconds_total": float(round(trident_wait_seconds, 4)),
            "analysis_fps_true": float(round(trident_stream_flows / trident_analysis_seconds, 4)) if trident_analysis_seconds > 0 else 0.0,
            "pipeline_fps_true": float(round(trident_pipeline_flows / trident_pipeline_seconds, 4)) if trident_pipeline_seconds > 0 else 0.0,
            "runtime_fps_true": float(round(trident_pipeline_flows / trident_runtime_seconds, 4)) if trident_runtime_seconds > 0 else 0.0,
            "stream_window_fps": float(round(trident_stream_flows / trident_stream_window_seconds, 4))
            if trident_stream_window_seconds > 0
            else 0.0,
            "compute_duty_cycle": float(
                round((trident_stream_window_seconds + trident_init_seconds) / trident_experiment_seconds, 6)
            )
            if trident_experiment_seconds > 0
            else 0.0,
            "wait_ratio": float(round(trident_wait_seconds / trident_experiment_seconds, 6))
            if trident_experiment_seconds > 0
            else 0.0,
            "reported_fps_end_to_end": _safe_float(trident_throughput.get("flows_per_second_end_to_end"), 0.0),
            "reported_fps_inference": _safe_float(trident_throughput.get("flows_per_second_inference"), 0.0),
            "resource": {
                "compute_device": str(trident_resource.get("compute_device", "")),
                "cpu_percent_one_core_avg": _safe_float(trident_resource.get("process_cpu_percent_one_core_avg"), 0.0),
                "cpu_percent_one_core_max": _safe_float(trident_resource.get("process_cpu_percent_one_core_max"), 0.0),
                "gpu_utilization_percent_avg": _safe_float(trident_resource.get("gpu_utilization_percent_avg"), 0.0),
                "gpu_utilization_percent_max": _safe_float(trident_resource.get("gpu_utilization_percent_max"), 0.0),
                "process_rss_peak_mb": _safe_float(trident_resource.get("process_rss_peak_mb"), 0.0),
                "gpu_memory_used_mb_max": _safe_float(trident_resource.get("gpu_memory_used_mb_max"), 0.0),
            },
        },
        "redis": {
            "xlen_max": _safe_int(redis_summary.get("xlen_max"), 0),
            "xlen_last": _safe_int(redis_summary.get("xlen_last"), 0),
            "used_memory_peak_max": _safe_int(redis_summary.get("used_memory_peak_max"), 0),
        },
    }


def write_trident_config(cfg: StressConfig) -> Path:
    trident_cfg = yaml.safe_load(cfg.trident_config.read_text(encoding="utf-8"))
    if not isinstance(trident_cfg, dict):
        raise ValueError(f"Trident config must be a mapping: {cfg.trident_config}")
    trident_cfg.setdefault("input", {})["source"] = "redis_stream"
    redis_cfg = trident_cfg["input"].setdefault("redis", {})
    redis_cfg["url"] = cfg.redis_url
    redis_cfg["data_structure"] = "stream"
    redis_cfg["key"] = cfg.redis_stream
    redis_cfg["stream"] = cfg.redis_stream
    redis_cfg["max_messages"] = cfg.redis_max_messages if cfg.redis_max_messages > 0 else 0
    redis_cfg["idle_timeout_seconds"] = cfg.redis_idle_timeout
    runtime_cfg = trident_cfg.setdefault("runtime", {})
    runtime_cfg["performance_benchmark"] = True
    if cfg.trident_max_rows > 0:
        runtime_cfg["max_rows"] = cfg.trident_max_rows
    else:
        runtime_cfg["max_rows"] = 0

    if cfg.perf_mode:
        runtime_cfg["perf_mode"] = True
        runtime_cfg["debug_overlap_enabled"] = False
        runtime_cfg["aggregate_overlap_enabled"] = False
        runtime_cfg["missing_value_report_enabled"] = False
        trident_cfg.setdefault("decision_tree", {})["enabled"] = False

        viz_cfg = trident_cfg.setdefault("visualization", {})
        viz_cfg["enabled"] = False
        viz_cfg["dataset_topology_enabled"] = False
        viz_cfg["learner_topology_enabled"] = False
        viz_cfg["metric_audit_enabled"] = False
        viz_cfg["live_flush_enabled"] = False

        stream_cfg = trident_cfg.setdefault("stream", {})
        if cfg.perf_window_size > 0:
            stream_cfg["window_size"] = int(cfg.perf_window_size)

        if cfg.perf_disable_new_learner:
            tmagnifier_cfg = trident_cfg.setdefault("tmagnifier", {})
            tmagnifier_cfg["cluster_trigger_size"] = max(
                int(tmagnifier_cfg.get("cluster_trigger_size", 0) or 0),
                10_000_000,
            )
            tmagnifier_cfg["new_class_min_size"] = max(
                int(tmagnifier_cfg.get("new_class_min_size", 0) or 0),
                10_000_000,
            )
    out = cfg.run_dir / "trident_config.yaml"
    out.write_text(yaml.safe_dump(trident_cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def run_trident_thread(cfg: StressConfig, trident_config_path: Path, holder: Dict[str, Any]) -> threading.Thread:
    def target() -> None:
        try:
            holder["ctx"] = run_pipeline(
                repo_root=REPO_ROOT,
                profile=cfg.trident_profile,
                config_path=str(trident_config_path),
                max_rows=cfg.trident_max_rows,
                benchmark=True,
                output_dir=str(cfg.trident_output_dir),
                skip_docker=True,
                no_inject=True,
            )
        except BaseException as exc:
            holder["error"] = repr(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def copy_suricata_logs(cfg: StressConfig) -> None:
    src_dir = cfg.compose_dir / "logs"
    for name in ("suricata.log", "stats.log"):
        src = src_dir / name
        if src.is_file():
            shutil.copy2(src, cfg.run_dir / name)


def write_suricata_metrics(cfg: StressConfig) -> Dict[str, Any]:
    docker_report = read_json(cfg.run_dir / "docker_metrics.json")
    samples = [r for r in docker_report.get("samples", []) if str(r.get("container")) == cfg.suricata_container]
    payload = {
        "container": cfg.suricata_container,
        "docker_sample_count": len(samples),
        "docker_samples": samples,
        "logs": {
            name: {
                "present": (cfg.run_dir / name).is_file(),
                "bytes": int((cfg.run_dir / name).stat().st_size) if (cfg.run_dir / name).is_file() else 0,
            }
            for name in ("suricata.log", "stats.log")
        },
    }
    write_json(cfg.run_dir / "suricata_metrics.json", payload)
    return payload


def write_markdown_summary(cfg: StressConfig, summary: Dict[str, Any]) -> None:
    lines = [
        "# Trident Demo E2E Stress",
        "",
        f"- run_id: `{cfg.run_id}`",
        f"- status: `{summary.get('status')}`",
        f"- redis_stream: `{cfg.redis_stream}`",
        f"- pcap: `{cfg.pcap}`",
        f"- iface: `{cfg.replay_iface}`",
        "",
        "## Stage timings",
        "",
        "| Stage | Seconds |",
        "|---|---:|",
    ]
    for key, value in (summary.get("stages_seconds") or {}).items():
        lines.append(f"| `{key}` | {float(value):.6f} |")
    trident_report = summary.get("trident_benchmark") or {}
    if trident_report:
        lines.extend(["", "## Trident", ""])
        lines.append(f"- flow_count: {trident_report.get('flow_count')}")
        lines.append(f"- stream_flow_count: {trident_report.get('stream_flow_count')}")
        for key, value in (trident_report.get("throughput_flows_per_second") or {}).items():
            lines.append(f"- {key}: {value}")
    redis_summary = (summary.get("redis") or {}).get("summary") or {}
    if redis_summary:
        lines.extend(["", "## Redis", ""])
        for key, value in redis_summary.items():
            lines.append(f"- {key}: {value}")
    replay_summary = summary.get("replay") or {}
    if replay_summary:
        lines.extend(["", "## Replay", ""])
        for key, value in replay_summary.items():
            lines.append(f"- {key}: {value}")
    derived_timing = summary.get("derived_timing") or {}
    if derived_timing:
        lines.extend(["", "## Derived timing", ""])
        for key, value in derived_timing.items():
            if isinstance(value, (int, float)):
                lines.append(f"- {key}: {float(value):.6f}")
            else:
                lines.append(f"- {key}: {value}")
    component_metrics = summary.get("derived_component_metrics") or {}
    if component_metrics:
        lines.extend(["", "## Component metrics", ""])
        suricata = component_metrics.get("suricata") or {}
        trident = component_metrics.get("trident") or {}
        if suricata:
            lines.append("- suricata:")
            lines.append(f"  - flow_fps_total: {suricata.get('flow_fps_total')}")
            lines.append(f"  - flow_fps_replay_only: {suricata.get('flow_fps_replay_only')}")
            lines.append(f"  - flow_fps_tail_only: {suricata.get('flow_fps_tail_only')}")
            lines.append(f"  - process_seconds_total: {suricata.get('process_seconds_total')}")
        if trident:
            lines.append("- trident:")
            lines.append(f"  - analysis_fps_true: {trident.get('analysis_fps_true')}")
            lines.append(f"  - pipeline_fps_true: {trident.get('pipeline_fps_true')}")
            lines.append(f"  - runtime_fps_true: {trident.get('runtime_fps_true')}")
            lines.append(f"  - analysis_seconds_total: {trident.get('analysis_seconds_total')}")
    (cfg.run_dir / "stress_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_derived_timing(summary_stages: Dict[str, float], trident_benchmark: Dict[str, Any]) -> Dict[str, float]:
    trident_stages = trident_benchmark.get("stages_seconds") or {}
    if not isinstance(trident_stages, dict):
        trident_stages = {}

    def as_float(value: Any) -> float:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return 0.0
        return num if num >= 0 else 0.0

    # Suricata 解析耗时：只统计回放完成后的解析等待，不包含 tcpreplay 发送时长。
    suricata_parse_total = as_float(summary_stages.get("wait_after_replay", 0.0))

    # Trident 分析耗时：按离散阶段求和，避免把 replay 生命周期并入 Trident 分析耗时。
    trident_analysis_keys = (
        "init_learners",
        "stream_inference",
        "stream_cluster",
        "stream_create_learner",
        "stream_retrain",
        "init_create_learner",
        "stream_window_total",
        "qualification_total",
    )
    trident_analysis_total = sum(as_float(trident_stages.get(key, 0.0)) for key in trident_analysis_keys)

    return {
        "replay_send_total_seconds": as_float(summary_stages.get("tcpreplay", 0.0)),
        "suricata_parse_total_seconds": suricata_parse_total,
        "trident_analysis_total_seconds": trident_analysis_total,
        "trident_pipeline_total_seconds": as_float(trident_stages.get("pipeline_total", 0.0)),
        "trident_thread_runtime_seconds": as_float(summary_stages.get("trident_thread_runtime", 0.0)),
    }


def run_stress(config_path: Path) -> Dict[str, Any]:
    cfg = load_config(config_path)
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    stage_start: Dict[str, float] = {}
    stages: Dict[str, float] = {}

    def start(name: str) -> None:
        stage_start[name] = time.perf_counter()

    def stop(name: str) -> None:
        stages[name] = stages.get(name, 0.0) + time.perf_counter() - stage_start.pop(name, time.perf_counter())

    resolved_cfg = cfg.raw.copy()
    resolved_cfg.setdefault("runtime", {})["run_id"] = cfg.run_id
    resolved_cfg.setdefault("redis", {})["stream"] = cfg.redis_stream
    (cfg.run_dir / "stress_config_resolved.yaml").write_text(
        yaml.safe_dump(resolved_cfg, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    write_json(
        cfg.run_dir / "workload_manifest.json",
        {
            "run_id": cfg.run_id,
            "created_at": utc_now(),
            "pcap": str(cfg.pcap),
            "redis_stream": cfg.redis_stream,
            "suricata_container": cfg.suricata_container,
        },
    )

    status = "finished"
    error = ""
    trident_holder: Dict[str, Any] = {}
    replay_summary: Dict[str, Any] = {}
    settle_summary: Dict[str, Any] = {}
    trident_thread: Optional[threading.Thread] = None
    trident_thread_started_at: Optional[float] = None
    xlen_before_replay = 0
    sampler = PeriodicSampler(cfg.sample_interval_seconds)
    sampler.add(lambda: sample_redis(cfg, sampler))
    sampler.add(lambda: sample_docker(cfg, sampler))
    start("wall_clock_total")
    try:
        start("preflight")
        preflight(cfg)
        stop("preflight")
        start("start_services")
        start_services(cfg)
        stop("start_services")
        start("baseline")
        sampler.start()
        time.sleep(max(0.0, cfg.baseline_seconds))
        stop("baseline")

        trident_config = write_trident_config(cfg)
        trident_thread_started_at = time.perf_counter()
        trident_thread = run_trident_thread(cfg, trident_config, trident_holder)
        time.sleep(2)

        try:
            xlen_before_replay = int(redis_client(cfg).xlen(cfg.redis_stream))
        except Exception:
            xlen_before_replay = 0

        start("tcpreplay")
        replay_summary = run_replay_until_load(cfg)
        stop("tcpreplay")

        start("wait_after_replay")
        settle_summary = wait_for_suricata_settle(cfg, redis_client(cfg))
        stop("wait_after_replay")

        stop_suricata_capture(cfg)

        trident_thread.join(timeout=max(1, cfg.trident_timeout_seconds))
        if trident_thread.is_alive():
            raise RuntimeError(f"Trident did not finish within {cfg.trident_timeout_seconds}s")
        if trident_holder.get("error"):
            raise RuntimeError(f"Trident failed: {trident_holder['error']}")
        if trident_thread_started_at is not None:
            stages["trident_thread_runtime"] = stages.get("trident_thread_runtime", 0.0) + (time.perf_counter() - trident_thread_started_at)
    except BaseException as exc:
        status = "failed"
        error = repr(exc)
        if trident_thread_started_at is not None:
            stages["trident_thread_runtime"] = stages.get("trident_thread_runtime", 0.0) + max(0.0, time.perf_counter() - trident_thread_started_at)
    finally:
        sampler.stop()
        copy_suricata_logs(cfg)
        suricata_metrics = write_suricata_metrics(cfg)
        stop_services(cfg)
        stop("wall_clock_total")

    trident_run_dir = ""
    ctx = trident_holder.get("ctx")
    if ctx is not None:
        trident_run_dir = str(ctx.output_dir)
        (cfg.run_dir / "trident_run_dir.txt").write_text(trident_run_dir + "\n", encoding="utf-8")
    trident_benchmark = read_json(Path(trident_run_dir) / "trident_performance_benchmark.json") if trident_run_dir else {}
    derived_timing = build_derived_timing(stages, trident_benchmark)
    # Backfill canonical non-overlap stage keys for downstream dashboards.
    stages["suricata_parse_total"] = float(derived_timing["suricata_parse_total_seconds"])
    stages["trident_total"] = float(derived_timing["trident_analysis_total_seconds"])
    redis_report = read_json(cfg.run_dir / "redis_metrics.json")
    docker_report = read_json(cfg.run_dir / "docker_metrics.json")
    component_metrics = build_component_metrics(
        cfg,
        replay_summary=replay_summary,
        settle_summary=settle_summary,
        trident_benchmark=trident_benchmark,
        redis_report=redis_report,
        docker_report=docker_report,
        xlen_before_replay=xlen_before_replay,
        derived_timing=derived_timing,
    )
    summary = {
        "version": 1,
        "run_id": cfg.run_id,
        "status": status,
        "error": error,
        "run_dir": str(cfg.run_dir),
        "trident_run_dir": trident_run_dir,
        "finished_at": utc_now(),
        "stages_seconds": stages,
        "redis": redis_report,
        "suricata": suricata_metrics,
        "docker": docker_report,
        "replay": replay_summary,
        "suricata_settle": settle_summary,
        "trident_benchmark": trident_benchmark,
        "derived_timing": derived_timing,
        "derived_component_metrics": component_metrics,
    }
    write_json(cfg.run_dir / "stress_summary.json", summary)
    write_markdown_summary(cfg, summary)
    print(json.dumps({"run_dir": str(cfg.run_dir), "status": status}, ensure_ascii=False, indent=2))
    if status != "finished":
        raise RuntimeError(error)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an isolated trident_demo E2E stress test.")
    parser.add_argument("config", nargs="?", default=str(DEFAULT_CONFIG), help="YAML stress config path.")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    run_stress(resolve_path(args.config))
