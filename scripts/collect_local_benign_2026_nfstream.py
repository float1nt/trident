#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from nfstream import NFStreamer


def _read_keep_columns(alignment_report_path: Path) -> List[str]:
    data = json.loads(alignment_report_path.read_text(encoding="utf-8"))
    cols = data.get("keep_columns")
    if not isinstance(cols, list) or not cols:
        raise ValueError(f"Invalid keep_columns in {alignment_report_path}")
    return [str(c) for c in cols]


def _as_num(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _get_attr(flow: Any, names: Sequence[str], default: float = 0.0) -> float:
    for n in names:
        if hasattr(flow, n):
            return _as_num(getattr(flow, n), default)
    return default


def _safe_rate(num: float, denom_sec: float) -> float:
    if denom_sec <= 1e-9:
        return 0.0
    return float(num / denom_sec)


def _to_timestamp_str(ms: float) -> str:
    if ms <= 0:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    return datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S.%f")


def _flow_to_row(flow: Any, keep_columns: Iterable[str]) -> Dict[str, Any]:
    keep_cols = list(keep_columns)
    row: Dict[str, Any] = {c: 0 for c in keep_cols}

    src_ip = str(getattr(flow, "src_ip", "0.0.0.0") or "0.0.0.0")
    dst_ip = str(getattr(flow, "dst_ip", "0.0.0.0") or "0.0.0.0")
    src_port = int(_get_attr(flow, ["src_port"], 0))
    dst_port = int(_get_attr(flow, ["dst_port"], 0))
    proto = int(_get_attr(flow, ["protocol"], 0))

    first_seen_ms = _get_attr(flow, ["bidirectional_first_seen_ms", "src2dst_first_seen_ms"], 0.0)
    duration_ms = _get_attr(flow, ["bidirectional_duration_ms"], 0.0)
    duration_sec = max(duration_ms / 1000.0, 1e-6)
    duration_us = int(max(duration_ms * 1000.0, 1.0))

    fwd_pkts = int(_get_attr(flow, ["src2dst_packets"], 0))
    bwd_pkts = int(_get_attr(flow, ["dst2src_packets"], 0))
    fwd_bytes = int(_get_attr(flow, ["src2dst_bytes"], 0))
    bwd_bytes = int(_get_attr(flow, ["dst2src_bytes"], 0))
    total_pkts = int(_get_attr(flow, ["bidirectional_packets"], fwd_pkts + bwd_pkts))
    total_bytes = int(_get_attr(flow, ["bidirectional_bytes"], fwd_bytes + bwd_bytes))

    pkt_min = _get_attr(flow, ["bidirectional_min_ps"], 0.0)
    pkt_max = _get_attr(flow, ["bidirectional_max_ps"], 0.0)
    pkt_mean = _get_attr(flow, ["bidirectional_mean_ps"], 0.0)
    pkt_std = _get_attr(flow, ["bidirectional_stddev_ps"], 0.0)

    fwd_pkt_min = _get_attr(flow, ["src2dst_min_ps"], 0.0)
    fwd_pkt_max = _get_attr(flow, ["src2dst_max_ps"], 0.0)
    fwd_pkt_mean = _get_attr(flow, ["src2dst_mean_ps"], 0.0)
    fwd_pkt_std = _get_attr(flow, ["src2dst_stddev_ps"], 0.0)

    bwd_pkt_min = _get_attr(flow, ["dst2src_min_ps"], 0.0)
    bwd_pkt_max = _get_attr(flow, ["dst2src_max_ps"], 0.0)
    bwd_pkt_mean = _get_attr(flow, ["dst2src_mean_ps"], 0.0)
    bwd_pkt_std = _get_attr(flow, ["dst2src_stddev_ps"], 0.0)

    flow_iat_mean_us = _get_attr(flow, ["bidirectional_mean_piat_ms"], 0.0) * 1000.0
    flow_iat_std_us = _get_attr(flow, ["bidirectional_stddev_piat_ms"], 0.0) * 1000.0
    flow_iat_max_us = _get_attr(flow, ["bidirectional_max_piat_ms"], 0.0) * 1000.0
    flow_iat_min_us = _get_attr(flow, ["bidirectional_min_piat_ms"], 0.0) * 1000.0

    fwd_iat_mean_us = _get_attr(flow, ["src2dst_mean_piat_ms"], 0.0) * 1000.0
    fwd_iat_std_us = _get_attr(flow, ["src2dst_stddev_piat_ms"], 0.0) * 1000.0
    fwd_iat_max_us = _get_attr(flow, ["src2dst_max_piat_ms"], 0.0) * 1000.0
    fwd_iat_min_us = _get_attr(flow, ["src2dst_min_piat_ms"], 0.0) * 1000.0

    bwd_iat_mean_us = _get_attr(flow, ["dst2src_mean_piat_ms"], 0.0) * 1000.0
    bwd_iat_std_us = _get_attr(flow, ["dst2src_stddev_piat_ms"], 0.0) * 1000.0
    bwd_iat_max_us = _get_attr(flow, ["dst2src_max_piat_ms"], 0.0) * 1000.0
    bwd_iat_min_us = _get_attr(flow, ["dst2src_min_piat_ms"], 0.0) * 1000.0

    flow_id = f"{src_ip}-{dst_ip}-{src_port}-{dst_port}-{proto}"
    row["Flow ID"] = flow_id
    row["Src IP"] = src_ip
    row["Src Port"] = src_port
    row["Dst IP"] = dst_ip
    row["Dst Port"] = dst_port
    row["Protocol"] = proto
    row["Timestamp"] = _to_timestamp_str(first_seen_ms)
    row["Flow Duration"] = duration_us
    row["Total Fwd Packet"] = fwd_pkts
    row["Total Bwd packets"] = bwd_pkts
    row["Total Length of Fwd Packet"] = fwd_bytes
    row["Total Length of Bwd Packet"] = bwd_bytes
    row["Fwd Packet Length Max"] = fwd_pkt_max
    row["Fwd Packet Length Min"] = fwd_pkt_min
    row["Fwd Packet Length Mean"] = fwd_pkt_mean
    row["Fwd Packet Length Std"] = fwd_pkt_std
    row["Bwd Packet Length Max"] = bwd_pkt_max
    row["Bwd Packet Length Min"] = bwd_pkt_min
    row["Bwd Packet Length Mean"] = bwd_pkt_mean
    row["Bwd Packet Length Std"] = bwd_pkt_std
    row["Flow Bytes/s"] = _safe_rate(total_bytes, duration_sec)
    row["Flow Packets/s"] = _safe_rate(total_pkts, duration_sec)
    row["Flow IAT Mean"] = flow_iat_mean_us
    row["Flow IAT Std"] = flow_iat_std_us
    row["Flow IAT Max"] = flow_iat_max_us
    row["Flow IAT Min"] = flow_iat_min_us
    row["Fwd IAT Total"] = int(max(_get_attr(flow, ["src2dst_duration_ms"], 0.0) * 1000.0, 0.0))
    row["Fwd IAT Mean"] = fwd_iat_mean_us
    row["Fwd IAT Std"] = fwd_iat_std_us
    row["Fwd IAT Max"] = fwd_iat_max_us
    row["Fwd IAT Min"] = fwd_iat_min_us
    row["Bwd IAT Total"] = int(max(_get_attr(flow, ["dst2src_duration_ms"], 0.0) * 1000.0, 0.0))
    row["Bwd IAT Mean"] = bwd_iat_mean_us
    row["Bwd IAT Std"] = bwd_iat_std_us
    row["Bwd IAT Max"] = bwd_iat_max_us
    row["Bwd IAT Min"] = bwd_iat_min_us
    row["Fwd Packets/s"] = _safe_rate(fwd_pkts, duration_sec)
    row["Bwd Packets/s"] = _safe_rate(bwd_pkts, duration_sec)
    row["Packet Length Min"] = pkt_min
    row["Packet Length Max"] = pkt_max
    row["Packet Length Mean"] = pkt_mean
    row["Packet Length Std"] = pkt_std
    row["Packet Length Variance"] = float(pkt_std * pkt_std)
    row["FIN Flag Count"] = int(_get_attr(flow, ["bidirectional_fin_packets"], 0))
    row["SYN Flag Count"] = int(_get_attr(flow, ["bidirectional_syn_packets"], 0))
    row["RST Flag Count"] = int(_get_attr(flow, ["bidirectional_rst_packets"], 0))
    row["PSH Flag Count"] = int(_get_attr(flow, ["bidirectional_psh_packets"], 0))
    row["ACK Flag Count"] = int(_get_attr(flow, ["bidirectional_ack_packets"], 0))
    row["URG Flag Count"] = int(_get_attr(flow, ["bidirectional_urg_packets"], 0))
    row["CWR Flag Count"] = int(_get_attr(flow, ["bidirectional_cwr_packets"], 0))
    row["ECE Flag Count"] = int(_get_attr(flow, ["bidirectional_ece_packets"], 0))
    row["Down/Up Ratio"] = float(bwd_pkts / fwd_pkts) if fwd_pkts > 0 else 0.0
    row["Average Packet Size"] = pkt_mean
    row["Fwd Segment Size Avg"] = fwd_pkt_mean
    row["Bwd Segment Size Avg"] = bwd_pkt_mean
    row["Subflow Fwd Packets"] = fwd_pkts
    row["Subflow Fwd Bytes"] = fwd_bytes
    row["Subflow Bwd Packets"] = bwd_pkts
    row["Subflow Bwd Bytes"] = bwd_bytes
    row["FWD Init Win Bytes"] = int(_get_attr(flow, ["src2dst_init_window_bytes"], 0))
    row["Bwd Init Win Bytes"] = int(_get_attr(flow, ["dst2src_init_window_bytes"], 0))
    row["Fwd Act Data Pkts"] = int(_get_attr(flow, ["src2dst_psh_packets"], 0))
    row["Fwd Seg Size Min"] = fwd_pkt_min
    row["Label"] = "2026|BENIGN"
    return row


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect true flow features with NFStream and append as 2026 benign.",
    )
    parser.add_argument(
        "--alignment-report",
        default="data/aligned_2017_2019/alignment_report.json",
        help="Path to alignment report with keep_columns.",
    )
    parser.add_argument(
        "--output-csv",
        default="data/aligned_2017_2019/2026_benign.csv",
        help="Destination csv path.",
    )
    parser.add_argument(
        "--interface",
        default="any",
        help="Capture interface, e.g. any/eno1/wlan0.",
    )
    parser.add_argument(
        "--active-timeout",
        type=int,
        default=120,
        help="NFStream active timeout in seconds.",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=30,
        help="NFStream idle timeout in seconds.",
    )
    parser.add_argument(
        "--truncate-output",
        action="store_true",
        help="Truncate output file before writing new rows.",
    )
    args = parser.parse_args()

    keep_columns = _read_keep_columns(Path(args.alignment_report))
    out_path = Path(args.output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if args.truncate_output and out_path.exists():
        out_path.unlink()

    file_exists = out_path.exists() and out_path.stat().st_size > 0
    with out_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keep_columns)
        if not file_exists:
            writer.writeheader()
            f.flush()

        print(
            f"[nfstream] start interface={args.interface} output={out_path}",
            flush=True,
        )
        print("[nfstream] label fixed as 2026|BENIGN", flush=True)

        streamer = NFStreamer(
            source=args.interface,
            statistical_analysis=True,
            idle_timeout=args.idle_timeout,
            active_timeout=args.active_timeout,
        )
        count = 0
        for flow in streamer:
            row = _flow_to_row(flow=flow, keep_columns=keep_columns)
            writer.writerow(row)
            count += 1
            if count % 50 == 0:
                f.flush()
                print(f"[nfstream] wrote_flows={count}", flush=True)


if __name__ == "__main__":
    main()
