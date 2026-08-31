from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from notification.telegram import send_telegram


IMMEDIATE_CHANGE_TYPES = {
    "NEW_ENTRY",
    "READY_TO_ENTRY",
    "WATCH_TO_ENTRY",
    "NEW_READY",
    "WATCH_TO_READY",
}


def _display(value: object, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, (int, float)):
        return f"{float(value):.{decimals}f}"
    return str(value)


def format_entry_alert(event: pd.Series | dict) -> str:
    row = dict(event)
    direction = row.get("direction") or "LONG"
    marker = "🟢" if direction == "LONG" else "🔴"
    return "\n".join(
        [
            f"{marker} CWP {direction} ENTRY | {row.get('market', '')}",
            "",
            f"{row.get('symbol', '')} {row.get('name', '')} · {row.get('setup', '')}".strip(),
            f"Close: {_display(row.get('close'))}",
            f"Regime: {row.get('regime', '—')}",
            f"Zhongshu: {_display(row.get('zs_zd'))} – {_display(row.get('zs_zg'))}",
            f"Wyckoff: {row.get('wyckoff', '—')}",
            f"Trigger: {row.get('trigger', '—')}",
            "",
            f"Model Entry: {_display(row.get('entry_price'))}",
            f"SL: {_display(row.get('sl'))}",
            f"TP1: {_display(row.get('tp1'))}",
            f"TP2: {_display(row.get('tp2'))}",
            "",
            f"Status: {row.get('previous_status', 'NONE')} → ENTRY",
            "Model signal only; not an order instruction.",
        ]
    )


def format_ready_alert(event: pd.Series | dict) -> str:
    row = dict(event)
    direction = row.get("direction") or "LONG"
    return "\n".join(
        [
            f"🟡 CWP {direction} READY | {row.get('market', '')}",
            "",
            f"{row.get('symbol', '')} {row.get('name', '')} · {row.get('setup', '')}".strip(),
            f"Close: {_display(row.get('close'))}",
            f"Regime: {row.get('regime', '—')}",
            f"Zhongshu: {_display(row.get('zs_zd'))} – {_display(row.get('zs_zg'))}",
            f"Waiting: {row.get('trigger', '—')}",
            f"Status: {row.get('previous_status', 'NONE')} → READY",
        ]
    )


def format_daily_summary(scan_df: pd.DataFrame, changes_df: pd.DataFrame, market: str) -> str:
    counts = scan_df["status"].value_counts().to_dict() if not scan_df.empty else {}
    lines = [
        f"CWP Daily Scan | {market.upper()}",
        str(pd.Timestamp.now().date()),
        "",
        " | ".join(f"{status}: {counts.get(status, 0)}" for status in ["ENTRY", "READY", "WATCH"]),
    ]
    sections = [
        ("NEW ENTRY", {"NEW_ENTRY", "READY_TO_ENTRY", "WATCH_TO_ENTRY"}),
        ("NEW READY", {"NEW_READY", "WATCH_TO_READY"}),
        ("DROPPED", {"DROPPED"}),
    ]
    for title, change_types in sections:
        rows = changes_df[changes_df["change_type"].isin(change_types)] if not changes_df.empty else pd.DataFrame()
        if rows.empty:
            continue
        lines.extend(["", title])
        for _, row in rows.head(15).iterrows():
            lines.append(f"{row.get('symbol')}  {row.get('setup', '—')}  {row.get('regime', '—')}")
        if len(rows) > 15:
            lines.append(f"… and {len(rows) - 15} more")
    return "\n".join(lines)


def build_notification_id(event: pd.Series | dict) -> str:
    row = dict(event)
    return "_".join(
        str(row.get(field, ""))
        for field in ["market", "symbol", "signal_date", "setup", "current_status"]
    )


def _load_sent(path: str | Path) -> set[str]:
    sent_path = Path(path)
    if not sent_path.exists():
        return set()
    return set(json.loads(sent_path.read_text(encoding="utf-8")))


def _save_sent(values: set[str], path: str | Path) -> None:
    sent_path = Path(path)
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    sent_path.write_text(json.dumps(sorted(values), ensure_ascii=False, indent=2), encoding="utf-8")


def notify_changes(
    changes_df: pd.DataFrame,
    sent_path: str | Path = "state/notifications.json",
    dry_run: bool = False,
) -> list[str]:
    sent = _load_sent(sent_path)
    messages: list[str] = []
    for _, event in changes_df.iterrows():
        if event["change_type"] not in IMMEDIATE_CHANGE_TYPES:
            continue
        notification_id = build_notification_id(event)
        if notification_id in sent:
            continue
        message = (
            format_entry_alert(event)
            if str(event["current_status"]) == "ENTRY"
            else format_ready_alert(event)
        )
        if not dry_run:
            send_telegram(message)
            sent.add(notification_id)
        messages.append(message)
    if not dry_run:
        _save_sent(sent, sent_path)
    return messages
