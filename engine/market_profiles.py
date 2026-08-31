from __future__ import annotations

from dataclasses import replace

from engine.models import MarketProfile


PROFILES: dict[str, MarketProfile] = {
    "hs300": MarketProfile(
        key="hs300",
        market_type="China A-Shares",
        timezone="Asia/Shanghai",
        currency="CNY",
        trade_direction="Long Only",
        tick_size=0.01,
    ),
    "sp500": MarketProfile(
        key="sp500",
        market_type="US Equities",
        timezone="America/New_York",
        currency="USD",
        trade_direction="Both",
        tick_size=0.01,
    ),
}


def get_market_profile(market: str, trade_direction: str | None = None) -> MarketProfile:
    key = market.lower().strip()
    if key not in PROFILES:
        raise ValueError(f"Unsupported market: {market!r}; choose hs300 or sp500")
    profile = PROFILES[key]
    if trade_direction is not None:
        if trade_direction not in {"Both", "Long Only", "Short Only"}:
            raise ValueError(f"Unsupported trade direction: {trade_direction!r}")
        profile = replace(profile, trade_direction=trade_direction)
    return profile
