#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from cicflowmeter.sniffer import create_sniffer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live flow capture using Python cicflowmeter (official API path).",
    )
    parser.add_argument(
        "--interface",
        default="eno1",
        help="Capture interface, e.g. eno1/wlp0s20f3/any.",
    )
    parser.add_argument(
        "--output-csv",
        default="data/aligned_2017_2019/2026_benign_cic_raw.csv",
        help="Raw CICFlowMeter output csv path.",
    )
    parser.add_argument(
        "--fields",
        default=None,
        help="Optional comma-separated cicflowmeter fields.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose cicflowmeter logging.",
    )
    args = parser.parse_args()

    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    sniffer, session = create_sniffer(
        input_file=None,
        input_interface=args.interface,
        output_mode="csv",
        output=str(out_csv),
        input_directory=None,
        fields=args.fields,
        verbose=args.verbose,
    )

    print(
        f"[cicflowmeter] start interface={args.interface} output={out_csv}",
        flush=True,
    )
    print(
        "[cicflowmeter] this is raw CIC feature output; label is not auto-added here",
        flush=True,
    )

    sniffer.start()
    try:
        sniffer.join()
    except KeyboardInterrupt:
        sniffer.stop()
    finally:
        if hasattr(session, "_gc_stop"):
            session._gc_stop.set()
            session._gc_thread.join(timeout=2.0)
        sniffer.join()
        session.flush_flows()
        print("[cicflowmeter] stopped and flushed flows", flush=True)


if __name__ == "__main__":
    main()
