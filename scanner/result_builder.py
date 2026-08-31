from __future__ import annotations

from pathlib import Path

import pandas as pd

from engine.models import ScanResult
from scanner.ranking import sort_results


def build_results(results: list[ScanResult]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    return sort_results(pd.DataFrame([result.to_dict() for result in results]))


def classify_results(result_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if result_df.empty:
        return {status: pd.DataFrame() for status in ["ENTRY", "READY", "WATCH", "NONE"]}
    return {
        status: result_df[result_df["status"] == status].copy()
        for status in ["ENTRY", "READY", "WATCH", "NONE"]
    }


def save_scan_outputs(result_df: pd.DataFrame, market: str, root: str | Path = ".") -> None:
    root_path = Path(root)
    latest_path = root_path / "output" / "latest" / f"{market}.csv"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(latest_path, index=False)

    classes = classify_results(result_df)
    alert_rows = pd.concat([classes["ENTRY"], classes["READY"]], ignore_index=True)
    alerts_path = root_path / "output" / "alerts" / f"{market}_current.csv"
    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    alert_rows.to_csv(alerts_path, index=False)

