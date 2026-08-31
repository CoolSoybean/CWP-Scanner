from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


ACTIVE_STATUSES = {"WATCH", "READY", "ENTRY"}


def load_watchlist_state(path: str | Path = "state/watchlist.csv") -> pd.DataFrame:
    state_path = Path(path)
    if not state_path.exists():
        return pd.DataFrame()
    return pd.read_csv(state_path, dtype={"symbol": str})


def classify_change(previous_status: str | None, current_status: str) -> str:
    previous = previous_status or "NONE"
    current = current_status or "NONE"
    if previous == current:
        return "UNCHANGED"
    if current == "ENTRY":
        return "NEW_ENTRY" if previous == "NONE" else f"{previous}_TO_ENTRY"
    if current == "READY":
        return "NEW_READY" if previous == "NONE" else f"{previous}_TO_READY"
    if current == "WATCH":
        return "NEW_WATCH" if previous == "NONE" else f"{previous}_TO_WATCH"
    if previous in ACTIVE_STATUSES and current == "NONE":
        return "DROPPED"
    return f"{previous}_TO_{current}"


def compare_scan_with_state(scan_df: pd.DataFrame, previous_state: pd.DataFrame) -> pd.DataFrame:
    current = scan_df.copy()
    if current.empty:
        current = pd.DataFrame(columns=["symbol", "market", "status"])
    previous_map = (
        previous_state.set_index(["market", "symbol"])["current_status"].to_dict()
        if not previous_state.empty
        else {}
    )

    changes: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for _, row in current.iterrows():
        key = (str(row["market"]), str(row["symbol"]))
        seen.add(key)
        previous_status = previous_map.get(key, "NONE")
        item = row.to_dict()
        item["previous_status"] = previous_status
        item["current_status"] = row["status"]
        item["change_type"] = classify_change(previous_status, str(row["status"]))
        changes.append(item)

    if not previous_state.empty:
        for _, old in previous_state.iterrows():
            key = (str(old["market"]), str(old["symbol"]))
            if key in seen or str(old["current_status"]) not in ACTIVE_STATUSES:
                continue
            item = old.to_dict()
            item["previous_status"] = old["current_status"]
            item["current_status"] = "NONE"
            item["status"] = "NONE"
            item["change_type"] = "DROPPED"
            changes.append(item)
    return pd.DataFrame(changes)


def update_watchlist(
    scan_df: pd.DataFrame,
    previous_state: pd.DataFrame,
    max_tracking_days: int = 15,
    as_of: str | None = None,
) -> pd.DataFrame:
    today = as_of or date.today().isoformat()
    previous_lookup = (
        previous_state.set_index(["market", "symbol"]).to_dict("index")
        if not previous_state.empty
        else {}
    )
    rows: list[dict] = []
    for _, current in scan_df.iterrows():
        status = str(current["status"])
        if status not in ACTIVE_STATUSES:
            continue
        key = (str(current["market"]), str(current["symbol"]))
        old = previous_lookup.get(key, {})
        first_seen = str(old.get("first_seen", today))
        days_tracked = int(old.get("days_tracked", 0)) + 1
        highest_rank = max(int(old.get("highest_status_rank", 0)), int(current["status_rank"]))
        if days_tracked > max_tracking_days and status == "WATCH":
            continue
        row = current.to_dict()
        row.update(
            {
                "first_seen": first_seen,
                "days_tracked": days_tracked,
                "previous_status": old.get("current_status", "NONE"),
                "current_status": status,
                "highest_status_rank": highest_rank,
                "last_seen": today,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def append_signal_history(
    changes_df: pd.DataFrame,
    path: str | Path = "state/signal_history.csv",
) -> None:
    material = changes_df[changes_df["change_type"] != "UNCHANGED"].copy()
    if material.empty:
        return
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    material.insert(0, "recorded_at", pd.Timestamp.utcnow().isoformat())
    write_header = not history_path.exists()
    material.to_csv(history_path, mode="a", header=write_header, index=False)


def save_watchlist_state(state_df: pd.DataFrame, path: str | Path = "state/watchlist.csv") -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_df.to_csv(state_path, index=False)

