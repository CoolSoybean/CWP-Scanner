from __future__ import annotations

import pandas as pd


DEFAULT_KEYS = ["date", "symbol"]
DEFAULT_FIELDS = ["status", "setup", "regime", "trigger", "zs_zd", "zs_zg"]


def compare_outputs(
    pine: pd.DataFrame,
    python: pd.DataFrame,
    keys: list[str] | None = None,
    fields: list[str] | None = None,
    numeric_tolerance: float = 1e-6,
) -> pd.DataFrame:
    keys = keys or DEFAULT_KEYS
    fields = fields or DEFAULT_FIELDS
    merged = pine.merge(python, on=keys, suffixes=("_pine", "_python"), how="outer", indicator=True)
    mismatches: list[dict] = []
    for _, row in merged.iterrows():
        for field in fields:
            left = row.get(f"{field}_pine")
            right = row.get(f"{field}_python")
            if pd.isna(left) and pd.isna(right):
                continue
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                equal = abs(float(left) - float(right)) <= numeric_tolerance
            else:
                equal = str(left) == str(right)
            if not equal:
                mismatches.append(
                    {
                        **{key: row.get(key) for key in keys},
                        "field": field,
                        "pine": left,
                        "python": right,
                        "merge_state": row.get("_merge"),
                    }
                )
    return pd.DataFrame(mismatches)

