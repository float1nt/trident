from pathlib import Path

from eda_common import run_eda


def main() -> None:
    files = sorted(Path("/home/data/2017").glob("*.csv"))
    out = Path("/home/sr/97/trident/docs/eda_2017")
    run_eda(dataset_name="CICIDS2017", files=files, output_dir=out, chunk_size=200_000)


if __name__ == "__main__":
    main()
