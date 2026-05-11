from pathlib import Path

from eda_common import run_eda


def main() -> None:
    files = [Path("/home/data/cicids2026.csv")]
    out = Path("/home/sr/97/trident/docs/eda_2026")
    run_eda(dataset_name="CICIDS2026", files=files, output_dir=out, chunk_size=200_000)


if __name__ == "__main__":
    main()
