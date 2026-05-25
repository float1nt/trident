"""Process CPU / GPU resource sampling for performance benchmarks."""
from __future__ import annotations

import os
import resource
import subprocess
import threading
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Dict, List, Optional

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None  # type: ignore


def _rss_bytes() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = float(usage.ru_maxrss)
    # Linux: KB; macOS: bytes
    if os.name != "nt" and rss < 10_000_000:
        return rss * 1024.0
    return rss


def _process_cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


@dataclass
class ResourceSnapshot:
    wall: float
    process_cpu_seconds: float
    rss_bytes: float
    gpu_allocated_bytes: Optional[float] = None
    gpu_reserved_bytes: Optional[float] = None
    gpu_utilization_percent: Optional[float] = None
    gpu_memory_used_mb: Optional[float] = None


@dataclass
class ResourceTracker:
    enabled: bool = True
    device: str = "cpu"
    sample_interval_sec: float = 0.25
    _stage_starts: Dict[str, ResourceSnapshot] = field(default_factory=dict)
    stage_cpu_seconds: Dict[str, float] = field(default_factory=dict)
    stage_gpu_peak_bytes: Dict[str, float] = field(default_factory=dict)
    _sampler_thread: Optional[threading.Thread] = None
    _sampler_stop: threading.Event = field(default_factory=threading.Event)
    _samples: List[Dict[str, float]] = field(default_factory=list)
    _peak_rss_bytes: float = 0.0
    _start_snapshot: Optional[ResourceSnapshot] = None
    _end_snapshot: Optional[ResourceSnapshot] = None
    _gpu_available: bool = False
    _gpu_device_name: Optional[str] = None

    def configure_device(self, device: str) -> None:
        self.device = str(device)
        self._gpu_available = (
            torch is not None
            and self.device.startswith("cuda")
            and torch.cuda.is_available()
        )
        if self._gpu_available:
            try:
                idx = int(str(self.device).split(":")[-1]) if ":" in str(self.device) else 0
                self._gpu_device_name = torch.cuda.get_device_name(idx)
            except Exception:
                self._gpu_device_name = "cuda"

    def _capture(self) -> ResourceSnapshot:
        gpu_allocated = None
        gpu_reserved = None
        gpu_util = None
        gpu_mem_used_mb = None
        if self._gpu_available and torch is not None:
            try:
                gpu_allocated = float(torch.cuda.memory_allocated())
                gpu_reserved = float(torch.cuda.memory_reserved())
            except Exception:
                pass
        smi = _nvidia_smi_snapshot()
        if smi is not None:
            gpu_util = smi.get("gpu_utilization_percent")
            gpu_mem_used_mb = smi.get("gpu_memory_used_mb")

        snap = ResourceSnapshot(
            wall=perf_counter(),
            process_cpu_seconds=_process_cpu_seconds(),
            rss_bytes=_rss_bytes(),
            gpu_allocated_bytes=gpu_allocated,
            gpu_reserved_bytes=gpu_reserved,
            gpu_utilization_percent=gpu_util,
            gpu_memory_used_mb=gpu_mem_used_mb,
        )
        self._peak_rss_bytes = max(self._peak_rss_bytes, snap.rss_bytes)
        return snap

    def start_run(self) -> None:
        if not self.enabled:
            return
        if self._gpu_available and torch is not None:
            try:
                torch.cuda.reset_peak_memory_stats()
            except Exception:
                pass
        self._start_snapshot = self._capture()
        self._sampler_stop.clear()
        self._samples.clear()
        self._sampler_thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._sampler_thread.start()

    def finish_run(self) -> None:
        if not self.enabled:
            return
        self._sampler_stop.set()
        if self._sampler_thread is not None:
            self._sampler_thread.join(timeout=2.0)
            self._sampler_thread = None
        self._end_snapshot = self._capture()

    def _sample_loop(self) -> None:
        last_cpu = _process_cpu_seconds()
        last_wall = perf_counter()
        while not self._sampler_stop.wait(self.sample_interval_sec):
            now_wall = perf_counter()
            now_cpu = _process_cpu_seconds()
            interval = max(1e-9, now_wall - last_wall)
            cpu_delta = max(0.0, now_cpu - last_cpu)
            sample = {
                "process_cpu_percent_one_core": cpu_delta / interval * 100.0,
                "rss_bytes": _rss_bytes(),
            }
            smi = _nvidia_smi_snapshot()
            if smi is not None:
                sample["gpu_utilization_percent"] = float(smi["gpu_utilization_percent"])
                sample["gpu_memory_used_mb"] = float(smi["gpu_memory_used_mb"])
            elif self._gpu_available and torch is not None:
                try:
                    sample["gpu_allocated_mb"] = torch.cuda.memory_allocated() / (1024.0 * 1024.0)
                except Exception:
                    pass
            self._samples.append(sample)
            self._peak_rss_bytes = max(self._peak_rss_bytes, sample["rss_bytes"])
            last_cpu = now_cpu
            last_wall = now_wall

    def mark_stage_start(self, key: str) -> None:
        if not self.enabled:
            return
        if self._gpu_available and torch is not None:
            try:
                torch.cuda.reset_peak_memory_stats()
            except Exception:
                pass
        self._stage_starts[key] = self._capture()

    def mark_stage_end(self, key: str) -> None:
        if not self.enabled:
            return
        start = self._stage_starts.pop(key, None)
        if start is None:
            return
        end = self._capture()
        cpu_delta = max(0.0, end.process_cpu_seconds - start.process_cpu_seconds)
        self.stage_cpu_seconds[key] = self.stage_cpu_seconds.get(key, 0.0) + cpu_delta
        if self._gpu_available and torch is not None:
            try:
                peak = float(torch.cuda.max_memory_allocated())
                prev = self.stage_gpu_peak_bytes.get(key, 0.0)
                self.stage_gpu_peak_bytes[key] = max(prev, peak)
            except Exception:
                pass

    def add_stage_cpu(self, key: str, cpu_seconds: float) -> None:
        if not self.enabled:
            return
        delta = max(0.0, float(cpu_seconds))
        self.stage_cpu_seconds[key] = self.stage_cpu_seconds.get(key, 0.0) + delta

    def current_process_cpu_seconds(self) -> float:
        return _process_cpu_seconds()

    def build_summary(self, wall_clock_seconds: float) -> Dict[str, Any]:
        if not self.enabled:
            return {}

        cpu_count = max(1, int(os.cpu_count() or 1))
        total_cpu = 0.0
        if self._start_snapshot and self._end_snapshot:
            total_cpu = max(
                0.0,
                self._end_snapshot.process_cpu_seconds - self._start_snapshot.process_cpu_seconds,
            )

        avg_cpu_pct = None
        max_cpu_pct = None
        if self._samples:
            one_core = [s["process_cpu_percent_one_core"] for s in self._samples]
            avg_cpu_pct = sum(one_core) / len(one_core)
            max_cpu_pct = max(one_core)

        avg_gpu_util = None
        max_gpu_util = None
        max_gpu_mem_mb = None
        gpu_utils = [
            s["gpu_utilization_percent"]
            for s in self._samples
            if "gpu_utilization_percent" in s
        ]
        if gpu_utils:
            avg_gpu_util = sum(gpu_utils) / len(gpu_utils)
            max_gpu_util = max(gpu_utils)
        gpu_mems = [s.get("gpu_memory_used_mb") for s in self._samples if "gpu_memory_used_mb" in s]
        if gpu_mems:
            max_gpu_mem_mb = max(gpu_mems)

        gpu_peak_allocated_mb = None
        gpu_peak_reserved_mb = None
        if self._gpu_available and torch is not None:
            try:
                gpu_peak_allocated_mb = torch.cuda.max_memory_allocated() / (1024.0 * 1024.0)
                gpu_peak_reserved_mb = torch.cuda.max_memory_reserved() / (1024.0 * 1024.0)
            except Exception:
                pass

        machine_avg_util = None
        if wall_clock_seconds > 0:
            machine_avg_util = total_cpu / (wall_clock_seconds * cpu_count)

        return {
            "compute_device": self.device,
            "gpu_available": bool(self._gpu_available),
            "gpu_device_name": self._gpu_device_name,
            "cpu_logical_count": cpu_count,
            "process_cpu_seconds_total": round(total_cpu, 6),
            "wall_clock_seconds": round(wall_clock_seconds, 6),
            "cpu_utilization_vs_cores_avg": (
                round(machine_avg_util, 6) if machine_avg_util is not None else None
            ),
            "process_cpu_percent_one_core_avg": (
                round(avg_cpu_pct, 2) if avg_cpu_pct is not None else None
            ),
            "process_cpu_percent_one_core_max": (
                round(max_cpu_pct, 2) if max_cpu_pct is not None else None
            ),
            "process_rss_peak_mb": round(self._peak_rss_bytes / (1024.0 * 1024.0), 3),
            "gpu_peak_allocated_mb": (
                round(gpu_peak_allocated_mb, 3) if gpu_peak_allocated_mb is not None else None
            ),
            "gpu_peak_reserved_mb": (
                round(gpu_peak_reserved_mb, 3) if gpu_peak_reserved_mb is not None else None
            ),
            "gpu_utilization_percent_avg": (
                round(avg_gpu_util, 2) if avg_gpu_util is not None else None
            ),
            "gpu_utilization_percent_max": (
                round(max_gpu_util, 2) if max_gpu_util is not None else None
            ),
            "gpu_memory_used_mb_max": (
                round(max_gpu_mem_mb, 3) if max_gpu_mem_mb is not None else None
            ),
            "stage_process_cpu_seconds": {
                k: round(v, 6) for k, v in sorted(self.stage_cpu_seconds.items())
            },
            "stage_gpu_peak_allocated_mb": {
                k: round(v / (1024.0 * 1024.0), 3)
                for k, v in sorted(self.stage_gpu_peak_bytes.items())
            },
            "sample_count": len(self._samples),
        }


def _nvidia_smi_snapshot() -> Optional[Dict[str, float]]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    line = proc.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 2:
        return None
    try:
        return {
            "gpu_utilization_percent": float(parts[0]),
            "gpu_memory_used_mb": float(parts[1]),
        }
    except ValueError:
        return None
