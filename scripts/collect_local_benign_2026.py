#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def _read_keep_columns(alignment_report_path: Path) -> List[str]:
    data = json.loads(alignment_report_path.read_text(encoding="utf-8"))
    cols = data.get("keep_columns")
    if not isinstance(cols, list) or not cols:
        raise ValueError(f"Invalid keep_columns in {alignment_report_path}")
    return [str(c) for c in cols]


def _read_netdev() -> Dict[str, Dict[str, int]]:
    stats: Dict[str, Dict[str, int]] = {}
    with Path("/proc/net/dev").open("r", encoding="utf-8") as f:
        lines = f.readlines()[2:]
    for line in lines:
        if ":" not in line:
            continue
        iface_raw, payload = line.split(":", 1)
        iface = iface_raw.strip()
        parts = payload.split()
        if len(parts) < 16:
            continue
        rx_bytes = int(parts[0])
        rx_packets = int(parts[1])
        tx_bytes = int(parts[8])
        tx_packets = int(parts[9])
        stats[iface] = {
            "rx_bytes": rx_bytes,
            "rx_packets": rx_packets,
            "tx_bytes": tx_bytes,
            "tx_packets": tx_packets,
        }
    return stats


def _get_primary_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        return "127.0.0.1"


def _build_row(
    columns: List[str],
    iface: str,
    src_ip: str,
    now: datetime,
    interval_sec: float,
    d_rx_bytes: int,
    d_rx_pkts: int,
    d_tx_bytes: int,
    d_tx_pkts: int,
) -> Dict[str, object]:
    total_packets = d_tx_pkts + d_rx_pkts
    total_bytes = d_tx_bytes + d_rx_bytes
    duration_us = int(max(interval_sec, 1e-6) * 1_000_000)
    flow_bps = float(total_bytes / max(interval_sec, 1e-6))
    flow_pps = float(total_packets / max(interval_sec, 1e-6))
    fwd_pps = float(d_tx_pkts / max(interval_sec, 1e-6))
    bwd_pps = float(d_rx_pkts / max(interval_sec, 1e-6))
    avg_pkt = float(total_bytes / total_packets) if total_packets > 0 else 0.0
    down_up_ratio = float(d_rx_pkts / d_tx_pkts) if d_tx_pkts > 0 else 0.0
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")

    row: Dict[str, object] = {c: 0 for c in columns}
    row["Flow ID"] = f"{src_ip}-0.0.0.0-0-0-0-{iface}-{int(now.timestamp())}"
    row["Src IP"] = src_ip
    row["Src Port"] = 0
    row["Dst IP"] = "0.0.0.0"
    row["Dst Port"] = 0
    row["Protocol"] = 0
    row["Timestamp"] = ts_str
    row["Flow Duration"] = duration_us
    row["Total Fwd Packet"] = d_tx_pkts
    row["Total Bwd packets"] = d_rx_pkts
    row["Total Length of Fwd Packet"] = d_tx_bytes
    row["Total Length of Bwd Packet"] = d_rx_bytes
    row["Flow Bytes/s"] = flow_bps
    row["Flow Packets/s"] = flow_pps
    row["Fwd Packets/s"] = fwd_pps
    row["Bwd Packets/s"] = bwd_pps
    row["Packet Length Min"] = avg_pkt
    row["Packet Length Max"] = avg_pkt
    row["Packet Length Mean"] = avg_pkt
    row["Packet Length Std"] = 0.0
    row["Packet Length Variance"] = 0.0
    row["Down/Up Ratio"] = down_up_ratio
    row["Average Packet Size"] = avg_pkt
    row["Subflow Fwd Packets"] = d_tx_pkts
    row["Subflow Fwd Bytes"] = d_tx_bytes
    row["Subflow Bwd Packets"] = d_rx_pkts
    row["Subflow Bwd Bytes"] = d_rx_bytes
    row["Active Mean"] = duration_us
    row["Active Std"] = 0.0
    row["Active Max"] = duration_us
    row["Active Min"] = duration_us
    row["Idle Mean"] = 0.0
    row["Idle Std"] = 0.0
    row["Idle Max"] = 0.0
    row["Idle Min"] = 0.0
    row["Label"] = "2026|BENIGN"
    return row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect local NIC stats in aligned CIC format and append as benign rows.",
    )
    parser.add_argument(
        "--alignment-report",
        default="data/aligned_2017_2019/alignment_report.json",
        help="Path to alignment report that contains keep_columns.",
    )
    parser.add_argument(
        "--output-csv",
        default="data/aligned_2017_2019/2026_benign.csv",
        help="Destination CSV (append mode).",
    )
    parser.add_argument(
        "--interval-sec",
        type=float,
        default=5.0,
        help="Sampling interval seconds.",
    )
    parser.add_argument(
        "--include-loopback",
        action="store_true",
        help="Include loopback interfaces (lo).",
    )
    args = parser.parse_args()

    alignment_report_path = Path(args.alignment_report)
    output_csv = Path(args.output_csv)
    interval_sec = max(0.5, float(args.interval_sec))
    keep_columns = _read_keep_columns(alignment_report_path)
    src_ip = _get_primary_ip()

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    file_exists = output_csv.exists() and output_csv.stat().st_size > 0
    f = output_csv.open("a", encoding="utf-8", newline="")
    writer = csv.DictWriter(f, fieldnames=keep_columns)
    if not file_exists:
        writer.writeheader()
        f.flush()

    print(
        f"[collector] start -> output={output_csv} interval={interval_sec}s src_ip={src_ip}",
        flush=True,
    )
    print("[collector] label fixed as 2026|BENIGN", flush=True)

    prev = _read_netdev()
    prev_t = time.time()
    while True:
        time.sleep(interval_sec)
        now_t = time.time()
        curr = _read_netdev()
        dt = max(now_t - prev_t, 1e-6)
        now = datetime.now()
        wrote = 0
        for iface, cstat in curr.items():
            if iface not in prev:
                continue
            if (not args.include_loopback) and iface.startswith("lo"):
                continue
            pstat = prev[iface]
            d_rx_bytes = max(0, cstat["rx_bytes"] - pstat["rx_bytes"])
            d_rx_pkts = max(0, cstat["rx_packets"] - pstat["rx_packets"])
            d_tx_bytes = max(0, cstat["tx_bytes"] - pstat["tx_bytes"])
            d_tx_pkts = max(0, cstat["tx_packets"] - pstat["tx_packets"])
            if d_rx_pkts == 0 and d_tx_pkts == 0 and d_rx_bytes == 0 and d_tx_bytes == 0:
                continue
            row = _build_row(
                columns=keep_columns,
                iface=iface,
                src_ip=src_ip,
                now=now,
                interval_sec=dt,
                d_rx_bytes=d_rx_bytes,
                d_rx_pkts=d_rx_pkts,
                d_tx_bytes=d_tx_bytes,
                d_tx_pkts=d_tx_pkts,
            )
            writer.writerow(row)
            wrote += 1
        f.flush()
        print(
            f"[collector] {now.strftime('%Y-%m-%d %H:%M:%S')} wrote_rows={wrote}",
            flush=True,
        )
        prev = curr
        prev_t = now_t


if __name__ == "__main__":
    main()
