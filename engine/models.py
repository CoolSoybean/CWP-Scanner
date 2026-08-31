from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import IntEnum
from typing import Any


class ScanStatus(IntEnum):
    NONE = 0
    WATCH = 1
    READY = 2
    ENTRY = 3

    @classmethod
    def parse(cls, value: str | int | "ScanStatus") -> "ScanStatus":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[value.upper()]


class FractalType(IntEnum):
    BOTTOM = -1
    NONE = 0
    TOP = 1


class ChanRegime(IntEnum):
    BEAR_ZS = -2
    BEAR_TREND = -1
    UNKNOWN = 0
    BULL_TREND = 1
    BULL_ZS = 2
    NEUTRAL_ZS = 3
    TRANSITION = 4


class WyckoffState(IntEnum):
    DISTRIBUTION = -2
    DISTRIB_WATCH = -1
    NEUTRAL = 0
    ACCUM_WATCH = 1
    ACCUMULATION = 2


class SetupCode(IntEnum):
    ZS_BREAKDOWN = -4
    THIRD_SELL = -3
    SECOND_SELL = -2
    UTAD = -1
    NONE = 0
    SPRING = 1
    SECOND_BUY = 2
    THIRD_BUY = 3
    ZS_BREAKOUT = 4


@dataclass(frozen=True)
class MarketProfile:
    key: str
    market_type: str
    timezone: str
    currency: str
    trade_direction: str = "Both"
    fractal_min_bars: int = 3
    stroke_min_atr: float = 1.0
    zs_position_bull: float = 0.65
    zs_position_bear: float = 0.35
    max_stored_strokes: int = 30
    second_point_max_bars: int = 20
    third_point_max_bars: int = 12
    vol_ma_length: int = 20
    wyc_test_max_bars: int = 20
    spring_confirm_bars: int = 5
    wyc_climax_range_atr: float = 1.5
    wyc_climax_volume: float = 1.5
    micro_fractal_bars: int = 2
    sweep_lookback: int = 5
    enable_zs_breakout_entry: bool = True
    rr_ratio1: float = 2.0
    rr_ratio2: float = 3.0
    sl_buffer_atr: float = 0.30
    risk_max_display_bars: int = 20
    hide_risk_after_trade_closed: bool = True
    tick_size: float = 0.01

    @property
    def allow_long(self) -> bool:
        if self.market_type == "China A-Shares":
            return True
        return self.trade_direction in {"Both", "Long Only"}

    @property
    def allow_short(self) -> bool:
        if self.market_type == "China A-Shares":
            return False
        return self.trade_direction in {"Both", "Short Only"}


@dataclass
class EngineState:
    stroke_prices: list[float] = field(default_factory=list)
    stroke_types: list[int] = field(default_factory=list)
    stroke_bars: list[int] = field(default_factory=list)
    latest_fractal_type: int = 0
    latest_fractal_price: float | None = None
    latest_fractal_bar: int | None = None
    zs_active: bool = False
    zs_zg: float | None = None
    zs_zd: float | None = None
    zs_gg: float | None = None
    zs_dd: float | None = None
    zs_start_bar: int | None = None
    prev_zs_zg: float | None = None
    prev_zs_zd: float | None = None
    last_zs_identity_bar: int | None = None
    bull_break_registered: bool = False
    bear_break_registered: bool = False
    chan_regime: int = int(ChanRegime.UNKNOWN)
    regime_before_zhongshu: int = int(ChanRegime.UNKNOWN)
    micro_swing_high: float | None = None
    micro_swing_high_bar: int | None = None
    micro_swing_low: float | None = None
    micro_swing_low_bar: int | None = None
    first_buy_active: bool = False
    first_buy_low: float | None = None
    first_buy_bar: int | None = None
    second_buy_pending: bool = False
    second_buy_low: float | None = None
    second_buy_confirm_high: float | None = None
    second_buy_pullback_bar: int | None = None
    first_sell_active: bool = False
    first_sell_high: float | None = None
    first_sell_bar: int | None = None
    second_sell_pending: bool = False
    second_sell_high: float | None = None
    second_sell_confirm_low: float | None = None
    second_sell_pullback_bar: int | None = None
    wyc_state: int = int(WyckoffState.NEUTRAL)
    wyc_climax_extreme: float | None = None
    wyc_climax_volume: float | None = None
    wyc_climax_bar: int | None = None
    spring_pending: bool = False
    spring_low: float | None = None
    spring_high: float | None = None
    spring_bar: int | None = None
    spring_target: float | None = None
    utad_pending: bool = False
    utad_high: float | None = None
    utad_low: float | None = None
    utad_bar: int | None = None
    utad_target: float | None = None
    third_buy_pending: bool = False
    third_sell_pending: bool = False
    third_buy_level: float | None = None
    third_sell_level: float | None = None
    third_buy_break_bar: int | None = None
    third_sell_break_bar: int | None = None
    third_buy_pullback_low: float | None = None
    third_sell_pullback_high: float | None = None
    active_risk_ready: bool = False
    active_risk_long: bool = False
    active_tp1_hit: bool = False
    active_trade_closed: bool = False
    active_entry_price: float | None = None
    active_sl_price: float | None = None
    active_tp1_price: float | None = None
    active_tp2_price: float | None = None
    active_entry_bar: int | None = None
    active_setup_text: str = ""
    trend: str = "NEUTRAL"
    regime: str = "Unknown"
    wyckoff: str = "Neutral"
    setup: str = "NONE"
    trigger: str = "Waiting"
    direction: str = ""
    status: ScanStatus = ScanStatus.NONE
    entry_price: float | None = None
    sl: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    current_events: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    symbol: str
    market: str
    signal_date: date
    close: float
    status: str
    status_rank: int
    setup: str
    regime: str
    wyckoff: str
    trigger: str
    direction: str = ""
    zs_zd: float | None = None
    zs_zg: float | None = None
    entry_price: float | None = None
    sl: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    name: str = ""
    sector: str = ""
    notes: str = ""
    engine_version: str = "1.8.5-source-port"

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["signal_date"] = self.signal_date.isoformat()
        return row

