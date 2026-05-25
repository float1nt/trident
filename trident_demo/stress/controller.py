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
    wait_after_replay_seconds: float
    sample_interval_seconds: float
    baseline_seconds: float
    trident_config: Path
    trident_max_rows: int
    trident_profile: str
    trident_output_dir: Path
    trident_timeout_seconds: int


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
    output_root = resolve_path(str(runtime.get("output_root", "trident_demo/stress_outputs")))
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
        wait_after_replay_seconds=float(runtime.get("wait_after_replay_seconds", 30.0) or 0.0),
        sample_interval_seconds=float(runtime.get("sample_interval_seconds", 1.0) or 1.0),
        baseline_seconds=float(runtime.get("baseline_seconds", 3.0) or 0.0),
        trident_config=resolve_path(str(trident.get("config", "trident_demo/configs/benchmark.yaml"))),
        trident_max_rows=int(trident.get("max_rows", redis.get("max_messages", 100000)) or 0),
        trident_profile=str(trident.get("profile", "benchmark")),
        trident_output_dir=(run_dir / "trident").resolve(),
        trident_timeout_seconds=int(trident.get("timeout_seconds", 86400) or 86400),
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
    if not shutil.which("tcpreplay"):
        errors.append("tcpreplay not found in PATH")
    if not cfg.compose_dir.joinpath("docker-compose.yml").is_file():
        errors.append(f"docker-compose.yml not found: {cfg.compose_dir / 'docker-compose.yml'}")
    if not cfg.trident_config.is_file():
        errors.append(f"Trident config not found: {cfg.trident_config}")
    if not cfg.pcap.is_file():
        errors.append(f"pcap not found: {cfg.pcap}")
    if errors:
        raise RuntimeError("; ".join(errors))

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


def stop_services(cfg: StressConfig) -> None:
    if cfg.suricata_stop_after_run:
        run_cmd(["docker", "compose", "down"], cwd=cfg.compose_dir, log_path=cfg.run_dir / "commands.log", check=False)


def tcpreplay_supports_mtu_trunc() -> bool:
    proc = run_cmd(["tcpreplay", "--help"], capture=True, check=False)
    return "--mtu-trunc" in (proc.stdout + proc.stderr)


def build_replay_cmd(cfg: StressConfig) -> List[str]:
    cmd = ["tcpreplay", "-i", cfg.replay_iface]
    if cfg.replay_mbps > 0:
        cmd.extend(["--mbps", str(cfg.replay_mbps)])
    elif cfg.replay_pps > 0:
        cmd.extend(["--pps", str(cfg.replay_pps)])
    elif cfg.replay_multiplier > 0:
        cmd.extend(["--multiplier", str(cfg.replay_multiplier)])
    else:
        cmd.append("--topspeed")
    if cfg.replay_loop > 1:
        cmd.extend(["--loop", str(cfg.replay_loop)])
    if cfg.replay_mtu_trunc in {"true", "yes", "1"}:
        if tcpreplay_supports_mtu_trunc():
            cmd.append("--mtu-trunc")
    elif cfg.replay_mtu_trunc == "auto" and tcpreplay_supports_mtu_trunc():
        cmd.append("--mtu-trunc")
    cmd.append(str(cfg.pcap))
    return cmd


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
    redis_cfg["max_messages"] = cfg.redis_max_messages
    redis_cfg["idle_timeout_seconds"] = cfg.redis_idle_timeout
    trident_cfg.setdefault("runtime", {})["performance_benchmark"] = True
    if cfg.trident_max_rows > 0:
        trident_cfg["runtime"]["max_rows"] = cfg.trident_max_rows
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
    (cfg.run_dir / "stress_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    trident_thread: Optional[threading.Thread] = None
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
        start("trident_total")
        trident_thread = run_trident_thread(cfg, trident_config, trident_holder)
        time.sleep(2)

        start("tcpreplay")
        run_cmd(build_replay_cmd(cfg), log_path=cfg.run_dir / "replay.log")
        stop("tcpreplay")

        start("wait_after_replay")
        time.sleep(max(0.0, cfg.wait_after_replay_seconds))
        stop("wait_after_replay")

        trident_thread.join(timeout=max(1, cfg.trident_timeout_seconds))
        if trident_thread.is_alive():
            raise RuntimeError(f"Trident did not finish within {cfg.trident_timeout_seconds}s")
        if trident_holder.get("error"):
            raise RuntimeError(f"Trident failed: {trident_holder['error']}")
        stop("trident_total")
    except BaseException as exc:
        status = "failed"
        error = repr(exc)
        if "trident_total" in stage_start:
            stop("trident_total")
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
    summary = {
        "version": 1,
        "run_id": cfg.run_id,
        "status": status,
        "error": error,
        "run_dir": str(cfg.run_dir),
        "trident_run_dir": trident_run_dir,
        "finished_at": utc_now(),
        "stages_seconds": stages,
        "redis": read_json(cfg.run_dir / "redis_metrics.json"),
        "suricata": suricata_metrics,
        "docker": read_json(cfg.run_dir / "docker_metrics.json"),
        "trident_benchmark": trident_benchmark,
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
