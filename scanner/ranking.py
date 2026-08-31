from __future__ import annotations

import pandas as pd


SETUP_PRIORITY = {
    "SPR": 4,
    "UTAD": 4,
    "3B": 3,
    "3S": 3,
    "2B": 2,
    "2S": 2,
    "BRK": 1,
    "BRK_SHORT": 1,
    "NONE": 0,
}


def sort_results(result_df: pd.DataFrame) -> pd.DataFrame:
    if result_df.empty:
        return result_df
    ranked = result_df.copy()
    ranked["setup_rank"] = ranked["setup"].map(SETUP_PRIORITY).fillna(0).astype(int)
    ranked = ranked.sort_values(
        ["status_rank", "setup_rank", "symbol"],
        ascending=[False, False, True],
    )
    return ranked.drop(columns="setup_rank").reset_index(drop=True)
