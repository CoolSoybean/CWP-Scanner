from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from parity.compare_outputs import compare_outputs


def run_parity(pine_path: str | Path, python_path: str | Path, output_path: str | Path) -> int:
    pine = pd.read_csv(pine_path)
    python = pd.read_csv(python_path)
    mismatches = compare_outputs(pine, python)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    mismatches.to_csv(output_path, index=False)
    return len(mismatches)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pine", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--output", default="output/parity_mismatches.csv")
    args = parser.parse_args()
    mismatch_count = run_parity(args.pine, args.python, args.output)
    print(f"Parity mismatches: {mismatch_count}")
    raise SystemExit(1 if mismatch_count else 0)


if __name__ == "__main__":
    main()
