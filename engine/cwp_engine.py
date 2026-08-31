from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from data.base import normalize_ohlcv, validate_ohlcv
from engine.models import (
    ChanRegime,
    EngineState,
    FractalType,
    MarketProfile,
    ScanResult,
    ScanStatus,
    SetupCode,
    WyckoffState,
)


ENGINE_VERSION = "1.8.5-source-port"


@dataclass(frozen=True)
class BarParameters:
    stroke_min_bars: int
    stroke_atr: float
    zs_tolerance_atr: float
    spring_tolerance_atr: float
    sl_buffer_atr: float
    climax_range_atr: float
    climax_volume: float
    st_tolerance_atr: float
    volume_hard_confirm: bool
    gap_sensitive: bool


def _at(history: list[dict] | pd.DataFrame, index: int):
    return history[index] if isinstance(history, list) else history.iloc[index]


def _round(value: float | None, tick_size: float) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(round(float(value) / tick_size) * tick_size, 6)


def _rma(series: pd.Series, length: int) -> pd.Series:
    """TradingView-compatible Wilder RMA seed and recurrence."""
    values = pd.to_numeric(series, errors="coerce").astype(float)
    result = pd.Series(float("nan"), index=values.index, dtype=float)
    valid = values.dropna()
    if len(valid) < length:
        return result
    seed_position = values.index.get_loc(valid.index[length - 1])
    seed_values = values.iloc[: seed_position + 1].dropna().iloc[-length:]
    previous = float(seed_values.mean())
    result.iloc[seed_position] = previous
    for position in range(seed_position + 1, len(values)):
        current = values.iloc[position]
        if pd.isna(current):
            continue
        previous = (previous * (length - 1) + float(current)) / length
        result.iloc[position] = previous
    return result


def _prepare_indicators(df: pd.DataFrame, profile: MarketProfile) -> pd.DataFrame:
    frame = normalize_ohlcv(df).copy()
    previous_close = frame["close"].shift(1)
    frame["true_range"] = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr14"] = _rma(frame["true_range"], 14)
    frame["atr_slow"] = frame["atr14"].rolling(100).mean()
    frame["vol_sma"] = frame["volume"].rolling(profile.vol_ma_length).mean()
    return frame


def _bar_parameters(row: pd.Series, profile: MarketProfile) -> BarParameters:
    atr = row["atr14"]
    atr_slow = row["atr_slow"]
    atr_ratio = float(atr / atr_slow) if pd.notna(atr) and pd.notna(atr_slow) and atr_slow > 0 else 1.0
    volatility_scale = 1.20 if atr_ratio > 1.30 else 0.85 if atr_ratio < 0.80 else 1.0

    if profile.market_type == "China A-Shares":
        values = (max(profile.fractal_min_bars, 5), 1.10, 0.25, 1.00, 0.25, 1.50, 1.50, 0.60, True, True)
    elif profile.market_type == "US Equities":
        values = (max(profile.fractal_min_bars, 4), 0.90, 0.30, 1.00, 0.30, 1.50, 1.50, 0.75, True, True)
    elif profile.market_type == "Crypto":
        values = (max(profile.fractal_min_bars, 4), 1.30, 0.50, 1.50, 0.50, 1.80, 1.30, 1.00, False, False)
    else:
        values = (
            max(profile.fractal_min_bars, 4),
            profile.stroke_min_atr,
            0.30,
            1.00,
            profile.sl_buffer_atr,
            profile.wyc_climax_range_atr,
            profile.wyc_climax_volume,
            0.75,
            True,
            True,
        )
    return BarParameters(
        stroke_min_bars=values[0],
        stroke_atr=values[1] * volatility_scale,
        zs_tolerance_atr=values[2] * volatility_scale,
        spring_tolerance_atr=values[3] * volatility_scale,
        sl_buffer_atr=values[4] * volatility_scale,
        climax_range_atr=values[5],
        climax_volume=values[6],
        st_tolerance_atr=values[7] * volatility_scale,
        volume_hard_confirm=values[8],
        gap_sensitive=values[9],
    )


def _confirmed_pivot(
    history: list[dict] | pd.DataFrame,
    index: int,
    field: str,
    left: int,
    right: int,
    is_high: bool,
) -> tuple[float | None, int | None]:
    candidate_index = index - right
    if candidate_index - left < 0 or candidate_index + right >= len(history):
        return None, None
    candidate = float(_at(history, candidate_index)[field])
    left_values = [float(_at(history, position)[field]) for position in range(candidate_index - left, candidate_index)]
    right_values = [float(_at(history, position)[field]) for position in range(candidate_index + 1, candidate_index + right + 1)]
    if is_high:
        confirmed = candidate > max(left_values) and candidate >= max(right_values)
    else:
        confirmed = candidate < min(left_values) and candidate <= min(right_values)
    return (candidate, candidate_index) if confirmed else (None, None)


def update_strokes(
    state: EngineState,
    history: list[dict] | pd.DataFrame,
    index: int,
    parameters: BarParameters,
    profile: MarketProfile,
) -> bool:
    if index < 2:
        return False
    raw_top = float(_at(history, index - 1)["high"]) > float(_at(history, index - 2)["high"]) and float(
        _at(history, index - 1)["high"]
    ) >= float(_at(history, index)["high"])
    raw_bottom = float(_at(history, index - 1)["low"]) < float(_at(history, index - 2)["low"]) and float(
        _at(history, index - 1)["low"]
    ) <= float(_at(history, index)["low"])
    fractal_atr = _at(history, index - 1)["atr14"]
    new_stroke = False

    def process(fractal_type: FractalType, candidate_price: float, candidate_bar: int) -> bool:
        if not state.stroke_prices:
            state.stroke_prices.append(candidate_price)
            state.stroke_types.append(int(fractal_type))
            state.stroke_bars.append(candidate_bar)
            state.latest_fractal_type = int(fractal_type)
            state.latest_fractal_price = candidate_price
            state.latest_fractal_bar = candidate_bar
            return True
        last_type = state.stroke_types[-1]
        last_price = state.stroke_prices[-1]
        last_bar = state.stroke_bars[-1]
        if last_type == int(fractal_type):
            more_extreme = candidate_price > last_price if fractal_type == FractalType.TOP else candidate_price < last_price
            if more_extreme:
                state.stroke_prices[-1] = candidate_price
                state.stroke_bars[-1] = candidate_bar
                state.latest_fractal_type = int(fractal_type)
                state.latest_fractal_price = candidate_price
                state.latest_fractal_bar = candidate_bar
            return False
        enough_bars = candidate_bar - last_bar >= parameters.stroke_min_bars
        move = candidate_price - last_price if fractal_type == FractalType.TOP else last_price - candidate_price
        enough_move = pd.notna(fractal_atr) and move >= float(fractal_atr) * parameters.stroke_atr
        if enough_bars and enough_move:
            state.stroke_prices.append(candidate_price)
            state.stroke_types.append(int(fractal_type))
            state.stroke_bars.append(candidate_bar)
            state.latest_fractal_type = int(fractal_type)
            state.latest_fractal_price = candidate_price
            state.latest_fractal_bar = candidate_bar
            return True
        return False

    if raw_top:
        new_stroke = process(FractalType.TOP, float(_at(history, index - 1)["high"]), index - 1) or new_stroke
    if raw_bottom:
        new_stroke = process(FractalType.BOTTOM, float(_at(history, index - 1)["low"]), index - 1) or new_stroke
    while len(state.stroke_prices) > profile.max_stored_strokes:
        state.stroke_prices.pop(0)
        state.stroke_types.pop(0)
        state.stroke_bars.pop(0)
    return new_stroke


def _stroke_structure(state: EngineState) -> tuple[bool, bool]:
    if len(state.stroke_prices) < 4:
        return False, False
    p0, p1, p2, p3 = state.stroke_prices[-4:]
    t0, t1, t2, t3 = state.stroke_types[-4:]
    alternating = (t0, t1, t2, t3) in {
        (int(FractalType.TOP), int(FractalType.BOTTOM), int(FractalType.TOP), int(FractalType.BOTTOM)),
        (int(FractalType.BOTTOM), int(FractalType.TOP), int(FractalType.BOTTOM), int(FractalType.TOP)),
    }
    if not alternating:
        return False, False
    return p2 > p0 and p3 > p1, p2 < p0 and p3 < p1


def _recent_strokes(state: EngineState) -> tuple[float | None, float | None, float | None, float | None]:
    highs = [price for price, kind in zip(reversed(state.stroke_prices), reversed(state.stroke_types)) if kind == int(FractalType.TOP)]
    lows = [price for price, kind in zip(reversed(state.stroke_prices), reversed(state.stroke_types)) if kind == int(FractalType.BOTTOM)]
    return (
        highs[0] if highs else None,
        highs[1] if len(highs) > 1 else None,
        lows[0] if lows else None,
        lows[1] if len(lows) > 1 else None,
    )


def update_zhongshu(state: EngineState) -> bool:
    if len(state.stroke_prices) < 4:
        return False
    s0, s1, s2, s3 = state.stroke_prices[-4:]
    h1, l1 = max(s0, s1), min(s0, s1)
    h2, l2 = max(s1, s2), min(s1, s2)
    h3, l3 = max(s2, s3), min(s2, s3)
    current_zg = min(h1, h2, h3)
    current_zd = max(l1, l2, l3)
    current_gg = max(h1, h2, h3)
    current_dd = min(l1, l2, l3)
    if current_zg <= current_zd:
        return False
    current_start = state.stroke_bars[-4]
    new_zhongshu = False
    if not state.zs_active:
        state.zs_active = True
        state.zs_zg, state.zs_zd = current_zg, current_zd
        state.zs_gg, state.zs_dd = current_gg, current_dd
        state.zs_start_bar = current_start
        state.last_zs_identity_bar = current_start
        new_zhongshu = True
    else:
        merged_zg = min(float(state.zs_zg), current_zg)
        merged_zd = max(float(state.zs_zd), current_zd)
        if merged_zg > merged_zd:
            state.zs_zg, state.zs_zd = merged_zg, merged_zd
            state.zs_gg = max(float(state.zs_gg), current_gg)
            state.zs_dd = min(float(state.zs_dd), current_dd)
        else:
            state.prev_zs_zg, state.prev_zs_zd = state.zs_zg, state.zs_zd
            state.zs_zg, state.zs_zd = current_zg, current_zd
            state.zs_gg, state.zs_dd = current_gg, current_dd
            state.zs_start_bar = current_start
            state.last_zs_identity_bar = current_start
            new_zhongshu = True
    if new_zhongshu:
        state.bull_break_registered = False
        state.bear_break_registered = False
    return new_zhongshu


def detect_regime(
    state: EngineState,
    close: float,
    bull_structure: bool,
    bear_structure: bool,
    profile: MarketProfile,
) -> int:
    zs_position = 0.5
    if state.zs_active and state.zs_zg is not None and state.zs_zd is not None and state.zs_zg > state.zs_zd:
        zs_position = (close - state.zs_zd) / (state.zs_zg - state.zs_zd)
    rising = state.prev_zs_zg is not None and state.zs_zd is not None and state.zs_zd > state.prev_zs_zg
    falling = state.prev_zs_zd is not None and state.zs_zg is not None and state.zs_zg < state.prev_zs_zd
    if state.bull_break_registered and bull_structure:
        return int(ChanRegime.BULL_TREND)
    if state.bear_break_registered and bear_structure:
        return int(ChanRegime.BEAR_TREND)
    if state.zs_active:
        if rising and bull_structure:
            return int(ChanRegime.BULL_TREND)
        if falling and bear_structure:
            return int(ChanRegime.BEAR_TREND)
        if zs_position >= profile.zs_position_bull and not bear_structure:
            return int(ChanRegime.BULL_ZS)
        if zs_position <= profile.zs_position_bear and not bull_structure:
            return int(ChanRegime.BEAR_ZS)
        return int(ChanRegime.NEUTRAL_ZS)
    if bull_structure:
        return int(ChanRegime.BULL_TREND)
    if bear_structure:
        return int(ChanRegime.BEAR_TREND)
    return int(ChanRegime.TRANSITION)


def _regime_text(regime: int) -> str:
    return {
        int(ChanRegime.BULL_TREND): "Bull Trend",
        int(ChanRegime.BEAR_TREND): "Bear Trend",
        int(ChanRegime.BULL_ZS): "Bullish Zhongshu",
        int(ChanRegime.BEAR_ZS): "Bearish Zhongshu",
        int(ChanRegime.NEUTRAL_ZS): "Neutral Zhongshu",
        int(ChanRegime.TRANSITION): "Transition",
    }.get(regime, "Unknown")


def _wyckoff_text(state: EngineState) -> str:
    if state.wyc_state == int(WyckoffState.ACCUM_WATCH):
        return "Accum Watch"
    if state.wyc_state == int(WyckoffState.DISTRIB_WATCH):
        return "Distrib Watch"
    if state.wyc_state == int(WyckoffState.ACCUMULATION):
        return "Re-Accumulation" if state.regime_before_zhongshu == int(ChanRegime.BULL_TREND) else "Accumulation"
    if state.wyc_state == int(WyckoffState.DISTRIBUTION):
        return "Re-Distribution" if state.regime_before_zhongshu == int(ChanRegime.BEAR_TREND) else "Distribution"
    return "Neutral"


def _update_micro_structure(state: EngineState, history: list[dict] | pd.DataFrame, index: int, profile: MarketProfile) -> tuple[float | None, float | None, bool, bool]:
    bars = profile.micro_fractal_bars
    pivot_high, high_bar = _confirmed_pivot(history, index, "high", bars, bars, True)
    pivot_low, low_bar = _confirmed_pivot(history, index, "low", bars, bars, False)
    if pivot_high is not None:
        state.micro_swing_high, state.micro_swing_high_bar = pivot_high, high_bar
    if pivot_low is not None:
        state.micro_swing_low, state.micro_swing_low_bar = pivot_low, low_bar
    row = _at(history, index)
    bull_bos = (
        state.micro_swing_high is not None
        and state.micro_swing_high_bar is not None
        and index > state.micro_swing_high_bar
        and float(row["close"]) > state.micro_swing_high
        and float(row["close"]) > float(row["open"])
    )
    bear_bos = (
        state.micro_swing_low is not None
        and state.micro_swing_low_bar is not None
        and index > state.micro_swing_low_bar
        and float(row["close"]) < state.micro_swing_low
        and float(row["close"]) < float(row["open"])
    )
    return pivot_high, pivot_low, bull_bos, bear_bos


def _update_second_points(
    state: EngineState,
    index: int,
    row: pd.Series,
    profile: MarketProfile,
    bull_structure: bool,
    bear_structure: bool,
    last_high: float | None,
    last_low: float | None,
    micro_pivot_high: float | None,
    micro_pivot_low: float | None,
    bull_bos: bool,
    bear_bos: bool,
) -> tuple[bool, bool, bool, bool]:
    potential_first_buy = bear_structure and not state.first_buy_active and last_high is not None and last_low is not None and float(row["close"]) > last_high and float(row["close"]) > float(row["open"])
    potential_first_sell = bull_structure and not state.first_sell_active and last_high is not None and last_low is not None and float(row["close"]) < last_low and float(row["close"]) < float(row["open"])
    if potential_first_buy:
        state.first_buy_active, state.first_buy_low, state.first_buy_bar = True, last_low, index
        state.second_buy_pending = False
        state.second_buy_low = state.second_buy_confirm_high = state.second_buy_pullback_bar = None
    if potential_first_sell:
        state.first_sell_active, state.first_sell_high, state.first_sell_bar = True, last_high, index
        state.second_sell_pending = False
        state.second_sell_high = state.second_sell_confirm_low = state.second_sell_pullback_bar = None
    first_buy_window = state.first_buy_active and state.first_buy_bar is not None and index > state.first_buy_bar and index - state.first_buy_bar <= profile.second_point_max_bars
    first_sell_window = state.first_sell_active and state.first_sell_bar is not None and index > state.first_sell_bar and index - state.first_sell_bar <= profile.second_point_max_bars
    if first_buy_window and micro_pivot_low is not None and state.first_buy_low is not None and micro_pivot_low > state.first_buy_low:
        state.second_buy_pending = True
        state.second_buy_low = micro_pivot_low
        state.second_buy_confirm_high = state.micro_swing_high
        state.second_buy_pullback_bar = index - profile.micro_fractal_bars
    if first_sell_window and micro_pivot_high is not None and state.first_sell_high is not None and micro_pivot_high < state.first_sell_high:
        state.second_sell_pending = True
        state.second_sell_high = micro_pivot_high
        state.second_sell_confirm_low = state.micro_swing_low
        state.second_sell_pullback_bar = index - profile.micro_fractal_bars
    second_buy_entry = profile.allow_long and state.second_buy_pending and state.second_buy_confirm_high is not None and float(row["close"]) > state.second_buy_confirm_high and bull_bos
    second_sell_entry = profile.allow_short and state.second_sell_pending and state.second_sell_confirm_low is not None and float(row["close"]) < state.second_sell_confirm_low and bear_bos
    second_buy_invalid = state.second_buy_pending and state.first_buy_low is not None and float(row["low"]) < state.first_buy_low
    second_sell_invalid = state.second_sell_pending and state.first_sell_high is not None and float(row["high"]) > state.first_sell_high
    first_buy_expired = state.first_buy_active and state.first_buy_bar is not None and index - state.first_buy_bar > profile.second_point_max_bars
    first_sell_expired = state.first_sell_active and state.first_sell_bar is not None and index - state.first_sell_bar > profile.second_point_max_bars
    if second_buy_entry or second_buy_invalid or first_buy_expired:
        state.first_buy_active = state.second_buy_pending = False
    if second_sell_entry or second_sell_invalid or first_sell_expired:
        state.first_sell_active = state.second_sell_pending = False
    return potential_first_buy, potential_first_sell, second_buy_entry, second_sell_entry


def update_wyckoff_state(
    state: EngineState,
    history: list[dict] | pd.DataFrame,
    index: int,
    parameters: BarParameters,
    profile: MarketProfile,
    new_zhongshu: bool,
) -> tuple[bool, bool, bool, bool, bool]:
    if new_zhongshu:
        state.wyc_state = int(WyckoffState.NEUTRAL)
        state.wyc_climax_extreme = state.wyc_climax_volume = state.wyc_climax_bar = None
    row = _at(history, index)
    atr_ref = _at(history, index - 1)["atr14"] if index > 0 else float("nan")
    vol_sma_ref = _at(history, index - 1)["vol_sma"] if index > 0 else float("nan")
    inside = state.zs_active and not state.bull_break_registered and not state.bear_break_registered
    zs_tol = float(atr_ref) * parameters.zs_tolerance_atr if pd.notna(atr_ref) else 0.0
    near_low = inside and state.zs_zd is not None and float(row["low"]) <= state.zs_zd + zs_tol
    near_high = inside and state.zs_zg is not None and float(row["high"]) >= state.zs_zg - zs_tol
    candle_range = float(row["high"] - row["low"])
    close_location = (float(row["close"]) - float(row["low"])) / candle_range if candle_range > 0 else 0.5
    wide = pd.notna(atr_ref) and candle_range >= float(atr_ref) * parameters.climax_range_atr
    high_volume = pd.notna(vol_sma_ref) and float(row["volume"]) >= float(vol_sma_ref) * parameters.climax_volume
    participation = high_volume if parameters.volume_hard_confirm else True
    sc_like = inside and near_low and wide and participation and close_location >= 0.35
    bc_like = inside and near_high and wide and participation and close_location <= 0.65
    if sc_like:
        state.wyc_state = int(WyckoffState.ACCUM_WATCH)
        state.wyc_climax_extreme, state.wyc_climax_volume, state.wyc_climax_bar = float(row["low"]), float(row["volume"]), index
    if bc_like:
        state.wyc_state = int(WyckoffState.DISTRIB_WATCH)
        state.wyc_climax_extreme, state.wyc_climax_volume, state.wyc_climax_bar = float(row["high"]), float(row["volume"]), index
    st_tolerance = float(atr_ref) * parameters.st_tolerance_atr if pd.notna(atr_ref) else 0.0
    test_window = state.wyc_climax_bar is not None and index > state.wyc_climax_bar and index - state.wyc_climax_bar <= profile.wyc_test_max_bars
    contracted = state.wyc_climax_volume is not None and float(row["volume"]) < state.wyc_climax_volume
    crypto_soft = profile.market_type == "Crypto" and pd.notna(vol_sma_ref) and float(row["volume"]) <= float(vol_sma_ref) * 1.20
    effort = contracted if parameters.volume_hard_confirm else contracted or crypto_soft
    accumulation_st = state.wyc_state == int(WyckoffState.ACCUM_WATCH) and test_window and state.wyc_climax_extreme is not None and abs(float(row["low"]) - state.wyc_climax_extreme) <= st_tolerance and effort
    distribution_st = state.wyc_state == int(WyckoffState.DISTRIB_WATCH) and test_window and state.wyc_climax_extreme is not None and abs(float(row["high"]) - state.wyc_climax_extreme) <= st_tolerance and effort
    if accumulation_st:
        state.wyc_state = int(WyckoffState.ACCUMULATION)
    if distribution_st:
        state.wyc_state = int(WyckoffState.DISTRIBUTION)
    expired = state.wyc_state in {int(WyckoffState.ACCUM_WATCH), int(WyckoffState.DISTRIB_WATCH)} and state.wyc_climax_bar is not None and index - state.wyc_climax_bar > profile.wyc_test_max_bars
    if expired:
        state.wyc_state = int(WyckoffState.NEUTRAL)
        state.wyc_climax_extreme = state.wyc_climax_volume = state.wyc_climax_bar = None
    return inside, sc_like, bc_like, accumulation_st, distribution_st


def _update_spring_utad(
    state: EngineState,
    history: list[dict] | pd.DataFrame,
    index: int,
    parameters: BarParameters,
    profile: MarketProfile,
    inside: bool,
    bull_bos: bool,
    bear_bos: bool,
) -> tuple[bool, bool, bool, bool]:
    row = _at(history, index)
    atr_ref = _at(history, index - 1)["atr14"] if index > 0 else float("nan")
    tolerance = float(atr_ref) * parameters.spring_tolerance_atr if pd.notna(atr_ref) else 0.0
    spring_event = inside and state.wyc_state == int(WyckoffState.ACCUMULATION) and state.zs_zd is not None and float(row["low"]) < state.zs_zd and float(row["low"]) >= state.zs_zd - tolerance and float(row["close"]) > state.zs_zd
    utad_event = inside and state.wyc_state == int(WyckoffState.DISTRIBUTION) and state.zs_zg is not None and float(row["high"]) > state.zs_zg and float(row["high"]) <= state.zs_zg + tolerance and float(row["close"]) < state.zs_zg and profile.market_type != "China A-Shares"
    if spring_event:
        state.spring_pending = True
        state.spring_low, state.spring_high, state.spring_bar, state.spring_target = float(row["low"]), float(row["high"]), index, state.zs_zg
    if utad_event:
        state.utad_pending = True
        state.utad_high, state.utad_low, state.utad_bar, state.utad_target = float(row["high"]), float(row["low"]), index, state.zs_zd
    spring_window = state.spring_pending and state.spring_bar is not None and index > state.spring_bar and index - state.spring_bar <= profile.spring_confirm_bars
    utad_window = state.utad_pending and state.utad_bar is not None and index > state.utad_bar and index - state.utad_bar <= profile.spring_confirm_bars
    spring_invalid = state.spring_pending and state.spring_low is not None and float(row["low"]) < state.spring_low
    utad_invalid = state.utad_pending and state.utad_high is not None and float(row["high"]) > state.utad_high
    spring_entry = profile.allow_long and spring_window and not spring_invalid and state.spring_high is not None and float(row["close"]) > state.spring_high and bull_bos
    utad_entry = profile.allow_short and utad_window and not utad_invalid and state.utad_low is not None and float(row["close"]) < state.utad_low and bear_bos
    spring_expired = state.spring_pending and state.spring_bar is not None and index - state.spring_bar > profile.spring_confirm_bars
    utad_expired = state.utad_pending and state.utad_bar is not None and index - state.utad_bar > profile.spring_confirm_bars
    if spring_entry or spring_invalid or spring_expired:
        state.spring_pending = False
    if utad_entry or utad_invalid or utad_expired:
        state.utad_pending = False
    return spring_event, utad_event, spring_entry, utad_entry


def _register_breaks(
    state: EngineState,
    history: list[dict] | pd.DataFrame,
    index: int,
    parameters: BarParameters,
) -> tuple[bool, bool, float]:
    row = _at(history, index)
    atr_ref = _at(history, index - 1)["atr14"] if index > 0 else float("nan")
    zs_tol = float(atr_ref) * parameters.zs_tolerance_atr if pd.notna(atr_ref) else 0.0
    gap_up = parameters.gap_sensitive and index > 0 and pd.notna(atr_ref) and float(row["open"]) > float(_at(history, index - 1)["high"]) + float(atr_ref) * 0.30
    gap_down = parameters.gap_sensitive and index > 0 and pd.notna(atr_ref) and float(row["open"]) < float(_at(history, index - 1)["low"]) - float(atr_ref) * 0.30
    bull = state.zs_active and not state.bull_break_registered and state.zs_zg is not None and (float(row["close"]) > state.zs_zg + zs_tol or (gap_up and float(row["close"]) > state.zs_zg))
    bear = state.zs_active and not state.bear_break_registered and state.zs_zd is not None and (float(row["close"]) < state.zs_zd - zs_tol or (gap_down and float(row["close"]) < state.zs_zd))
    if bull:
        state.bull_break_registered = True
    if bear:
        state.bear_break_registered = True
    return bull, bear, zs_tol


def _update_third_points(
    state: EngineState,
    index: int,
    row: pd.Series,
    profile: MarketProfile,
    fresh_bull_break: bool,
    fresh_bear_break: bool,
    zs_tol: float,
    bull_bos: bool,
    bear_bos: bool,
) -> tuple[bool, bool]:
    if fresh_bull_break:
        state.third_buy_pending, state.third_sell_pending = True, False
        state.third_buy_level, state.third_buy_break_bar, state.third_buy_pullback_low = state.zs_zg, index, None
    if fresh_bear_break:
        state.third_sell_pending, state.third_buy_pending = True, False
        state.third_sell_level, state.third_sell_break_bar, state.third_sell_pullback_high = state.zs_zd, index, None
    third_buy_window = state.third_buy_pending and state.third_buy_break_bar is not None and index > state.third_buy_break_bar and index - state.third_buy_break_bar <= profile.third_point_max_bars
    third_sell_window = state.third_sell_pending and state.third_sell_break_bar is not None and index > state.third_sell_break_bar and index - state.third_sell_break_bar <= profile.third_point_max_bars
    third_buy_retest = third_buy_window and state.third_buy_level is not None and float(row["low"]) <= state.third_buy_level + zs_tol and float(row["low"]) >= state.third_buy_level - zs_tol and float(row["close"]) > state.third_buy_level
    third_sell_retest = third_sell_window and state.third_sell_level is not None and float(row["high"]) >= state.third_sell_level - zs_tol and float(row["high"]) <= state.third_sell_level + zs_tol and float(row["close"]) < state.third_sell_level
    if third_buy_retest:
        state.third_buy_pullback_low = float(row["low"])
    if third_sell_retest:
        state.third_sell_pullback_high = float(row["high"])
    third_buy_entry = profile.allow_long and third_buy_retest and bull_bos
    third_sell_entry = profile.allow_short and third_sell_retest and bear_bos
    third_buy_expired = state.third_buy_pending and state.third_buy_break_bar is not None and index - state.third_buy_break_bar > profile.third_point_max_bars
    third_sell_expired = state.third_sell_pending and state.third_sell_break_bar is not None and index - state.third_sell_break_bar > profile.third_point_max_bars
    third_buy_invalid = state.third_buy_pending and state.third_buy_level is not None and float(row["close"]) < state.third_buy_level - zs_tol
    third_sell_invalid = state.third_sell_pending and state.third_sell_level is not None and float(row["close"]) > state.third_sell_level + zs_tol
    if third_buy_entry or third_buy_expired or third_buy_invalid:
        state.third_buy_pending = False
    if third_sell_entry or third_sell_expired or third_sell_invalid:
        state.third_sell_pending = False
    return third_buy_entry, third_sell_entry


def _setup_name(code: int) -> str:
    return {
        int(SetupCode.SPRING): "SPR",
        int(SetupCode.SECOND_BUY): "2B",
        int(SetupCode.THIRD_BUY): "3B",
        int(SetupCode.ZS_BREAKOUT): "BRK",
        int(SetupCode.UTAD): "UTAD",
        int(SetupCode.SECOND_SELL): "2S",
        int(SetupCode.THIRD_SELL): "3S",
        int(SetupCode.ZS_BREAKDOWN): "BRK_SHORT",
    }.get(code, "NONE")


def calculate_trade_levels(
    state: EngineState,
    history: list[dict] | pd.DataFrame,
    index: int,
    parameters: BarParameters,
    profile: MarketProfile,
    long_entry: bool,
    short_entry: bool,
    active_setup: int,
) -> bool:
    row = _at(history, index)
    atr_ref = _at(history, index - 1)["atr14"] if index > 0 else float("nan")
    new_risk_set = False

    def install(long_side: bool, sl_anchor: float, target: float | None, text: str) -> bool:
        if pd.isna(atr_ref):
            return False
        close = float(row["close"])
        sl_price = sl_anchor - float(atr_ref) * parameters.sl_buffer_atr if long_side else sl_anchor + float(atr_ref) * parameters.sl_buffer_atr
        risk = close - sl_price if long_side else sl_price - close
        if risk <= profile.tick_size:
            return False
        fallback_tp1 = close + risk * profile.rr_ratio1 if long_side else close - risk * profile.rr_ratio1
        valid_target = target is not None and (target > close if long_side else target < close)
        tp1 = float(target) if valid_target else fallback_tp1
        tp2 = close + risk * profile.rr_ratio2 if long_side else close - risk * profile.rr_ratio2
        state.active_risk_ready = True
        state.active_risk_long = long_side
        state.active_tp1_hit = False
        state.active_trade_closed = False
        state.active_entry_price, state.active_sl_price = close, sl_price
        state.active_tp1_price, state.active_tp2_price = tp1, tp2
        state.active_entry_bar, state.active_setup_text = index, text
        return True

    if long_entry and pd.notna(atr_ref):
        sl_anchor, target, text = float(row["low"]), None, "Long"
        if active_setup == int(SetupCode.SPRING):
            sl_anchor, target, text = state.spring_low if state.spring_low is not None else float(row["low"]), state.spring_target, "Spring Long"
        elif active_setup == int(SetupCode.SECOND_BUY):
            sl_anchor, text = state.second_buy_low if state.second_buy_low is not None else float(row["low"]), "2B Long"
        elif active_setup == int(SetupCode.THIRD_BUY):
            sl_anchor, text = state.third_buy_pullback_low if state.third_buy_pullback_low is not None else float(row["low"]), "3B / LPS Long"
        elif active_setup == int(SetupCode.ZS_BREAKOUT):
            sl_anchor, text = min(float(row["low"]), state.zs_zg) if state.zs_zg is not None else float(row["low"]), "BRK Long"
        new_risk_set = install(True, float(sl_anchor), target, text) or new_risk_set
    if short_entry and pd.notna(atr_ref):
        sl_anchor, target, text = float(row["high"]), None, "Short"
        if active_setup == int(SetupCode.UTAD):
            sl_anchor, target, text = state.utad_high if state.utad_high is not None else float(row["high"]), state.utad_target, "UTAD Short"
        elif active_setup == int(SetupCode.SECOND_SELL):
            sl_anchor, text = state.second_sell_high if state.second_sell_high is not None else float(row["high"]), "2S Short"
        elif active_setup == int(SetupCode.THIRD_SELL):
            sl_anchor, text = state.third_sell_pullback_high if state.third_sell_pullback_high is not None else float(row["high"]), "3S / LPSY Short"
        elif active_setup == int(SetupCode.ZS_BREAKDOWN):
            sl_anchor, text = max(float(row["high"]), state.zs_zd) if state.zs_zd is not None else float(row["high"]), "BRK Short"
        new_risk_set = install(False, float(sl_anchor), target, text) or new_risk_set
    if new_risk_set:
        state.entry_price = state.active_entry_price
        state.sl = state.active_sl_price
        state.tp1 = state.active_tp1_price
        state.tp2 = state.active_tp2_price
    return new_risk_set


def _update_risk_lifecycle(state: EngineState, row: pd.Series, index: int, profile: MarketProfile) -> None:
    eligible = state.active_risk_ready and not state.active_trade_closed and state.active_entry_bar is not None and index > state.active_entry_bar
    if eligible:
        if state.active_risk_long:
            sl_hit = float(row["low"]) <= float(state.active_sl_price)
            tp1_hit = float(row["high"]) >= float(state.active_tp1_price)
            tp2_hit = float(row["high"]) >= float(state.active_tp2_price)
        else:
            sl_hit = float(row["high"]) >= float(state.active_sl_price)
            tp1_hit = float(row["low"]) <= float(state.active_tp1_price)
            tp2_hit = float(row["low"]) <= float(state.active_tp2_price)
        if tp1_hit:
            state.active_tp1_hit = True
        if sl_hit or tp2_hit:
            state.active_trade_closed = True
    if state.active_trade_closed and profile.hide_risk_after_trade_closed:
        state.active_risk_ready = False
    if state.active_risk_ready and state.active_entry_bar is not None and index - state.active_entry_bar > profile.risk_max_display_bars:
        state.active_risk_ready = False


def _derive_scanner_state(state: EngineState, profile: MarketProfile, active_setup: int, long_entry: bool, short_entry: bool, bull_bos: bool, bear_bos: bool) -> None:
    state.regime = _regime_text(state.chan_regime)
    state.wyckoff = _wyckoff_text(state)
    state.trend = "BULL" if state.chan_regime in {int(ChanRegime.BULL_TREND), int(ChanRegime.BULL_ZS)} else "BEAR" if state.chan_regime in {int(ChanRegime.BEAR_TREND), int(ChanRegime.BEAR_ZS)} else "NEUTRAL"
    state.direction = "SHORT" if short_entry else "LONG" if long_entry else ""
    if long_entry or short_entry:
        state.status = ScanStatus.ENTRY
        state.setup = _setup_name(active_setup)
    else:
        pending = [
            (state.spring_pending, "SPR", "LONG"),
            (state.utad_pending, "UTAD", "SHORT"),
            (state.second_buy_pending, "2B", "LONG"),
            (state.second_sell_pending, "2S", "SHORT"),
            (state.third_buy_pending, "3B", "LONG"),
            (state.third_sell_pending, "3S", "SHORT"),
        ]
        selected = next(((setup, direction) for enabled, setup, direction in pending if enabled), None)
        if selected:
            state.status, state.setup, state.direction = ScanStatus.READY, selected[0], selected[1]
        elif profile.market_type == "China A-Shares" and state.chan_regime == int(ChanRegime.BEAR_TREND):
            state.status, state.setup = ScanStatus.NONE, "NONE"
        elif state.chan_regime not in {int(ChanRegime.UNKNOWN), int(ChanRegime.TRANSITION)} or state.wyc_state != int(WyckoffState.NEUTRAL):
            state.status, state.setup = ScanStatus.WATCH, "NONE"
        else:
            state.status, state.setup = ScanStatus.NONE, "NONE"
    state.trigger = "Bull Micro BOS" if bull_bos else "Bear Micro BOS" if bear_bos else "Waiting"


def _process_bar(state: EngineState, history: list[dict] | pd.DataFrame, bar_date, index: int, profile: MarketProfile) -> dict:
    row = _at(history, index)
    state.entry_price = state.sl = state.tp1 = state.tp2 = None
    state.direction = ""
    parameters = _bar_parameters(row, profile)
    new_stroke = update_strokes(state, history, index, parameters, profile)
    bull_structure, bear_structure = _stroke_structure(state)
    last_high, previous_high, last_low, previous_low = _recent_strokes(state)
    new_zhongshu = update_zhongshu(state)
    state.chan_regime = detect_regime(state, float(row["close"]), bull_structure, bear_structure, profile)
    if new_zhongshu:
        state.regime_before_zhongshu = int(ChanRegime.BULL_TREND) if bull_structure else int(ChanRegime.BEAR_TREND) if bear_structure else int(ChanRegime.TRANSITION)
    micro_high, micro_low, bull_bos, bear_bos = _update_micro_structure(state, history, index, profile)
    if index >= profile.sweep_lookback:
        sweep_low = min(float(_at(history, position)["low"]) for position in range(index - profile.sweep_lookback, index))
        sweep_high = max(float(_at(history, position)["high"]) for position in range(index - profile.sweep_lookback, index))
        bull_sweep = float(row["low"]) < sweep_low and float(row["close"]) > sweep_low and float(row["close"]) > float(row["open"])
        bear_sweep = float(row["high"]) > sweep_high and float(row["close"]) < sweep_high and float(row["close"]) < float(row["open"])
    else:
        bull_sweep = bear_sweep = False
    bullish_engulfing = index > 0 and float(row["close"]) > float(row["open"]) and float(_at(history, index - 1)["close"]) < float(_at(history, index - 1)["open"]) and float(row["close"]) >= float(_at(history, index - 1)["open"]) and float(row["open"]) <= float(_at(history, index - 1)["close"])
    bearish_engulfing = index > 0 and float(row["close"]) < float(row["open"]) and float(_at(history, index - 1)["close"]) > float(_at(history, index - 1)["open"]) and float(row["close"]) <= float(_at(history, index - 1)["open"]) and float(row["open"]) >= float(_at(history, index - 1)["close"])
    potential_1b, potential_1s, second_buy_entry, second_sell_entry = _update_second_points(
        state, index, row, profile, bull_structure, bear_structure, last_high, last_low, micro_high, micro_low, bull_bos, bear_bos
    )
    inside, sc_like, bc_like, accumulation_st, distribution_st = update_wyckoff_state(
        state, history, index, parameters, profile, new_zhongshu
    )
    spring_event, utad_event, spring_entry, utad_entry = _update_spring_utad(
        state, history, index, parameters, profile, inside, bull_bos, bear_bos
    )
    fresh_bull_break, fresh_bear_break, zs_tol = _register_breaks(state, history, index, parameters)
    direct_long = profile.enable_zs_breakout_entry and profile.allow_long and fresh_bull_break and bull_bos
    direct_short = profile.enable_zs_breakout_entry and profile.allow_short and fresh_bear_break and bear_bos
    third_buy_entry, third_sell_entry = _update_third_points(
        state, index, row, profile, fresh_bull_break, fresh_bear_break, zs_tol, bull_bos, bear_bos
    )
    long_entry, short_entry, active_setup = False, False, int(SetupCode.NONE)
    if spring_entry:
        long_entry, active_setup = True, int(SetupCode.SPRING)
    elif second_buy_entry:
        long_entry, active_setup = True, int(SetupCode.SECOND_BUY)
    elif third_buy_entry:
        long_entry, active_setup = True, int(SetupCode.THIRD_BUY)
    elif direct_long:
        long_entry, active_setup = True, int(SetupCode.ZS_BREAKOUT)
    if utad_entry:
        short_entry, active_setup = True, int(SetupCode.UTAD)
    elif second_sell_entry:
        short_entry, active_setup = True, int(SetupCode.SECOND_SELL)
    elif third_sell_entry:
        short_entry, active_setup = True, int(SetupCode.THIRD_SELL)
    elif direct_short:
        short_entry, active_setup = True, int(SetupCode.ZS_BREAKDOWN)
    if profile.market_type == "China A-Shares":
        short_entry = False
    new_risk_set = calculate_trade_levels(
        state, history, index, parameters, profile, long_entry, short_entry, active_setup
    )
    _update_risk_lifecycle(state, row, index, profile)
    _derive_scanner_state(state, profile, active_setup, long_entry, short_entry, bull_bos, bear_bos)
    events = {
        "new_stroke": new_stroke,
        "new_zhongshu": new_zhongshu,
        "bull_stroke_structure": bull_structure,
        "bear_stroke_structure": bear_structure,
        "potential_first_buy": potential_1b,
        "potential_first_sell": potential_1s,
        "sc_like": sc_like,
        "bc_like": bc_like,
        "accumulation_st": accumulation_st,
        "distribution_st": distribution_st,
        "spring_event": spring_event,
        "utad_event": utad_event,
        "fresh_bullish_zs_break": fresh_bull_break,
        "fresh_bearish_zs_break": fresh_bear_break,
        "bull_micro_bos": bull_bos,
        "bear_micro_bos": bear_bos,
        "bull_sweep": bull_sweep,
        "bear_sweep": bear_sweep,
        "bullish_engulfing": bullish_engulfing,
        "bearish_engulfing": bearish_engulfing,
        "spring_entry": spring_entry,
        "second_buy_entry": second_buy_entry,
        "third_buy_entry": third_buy_entry,
        "zs_breakout_long_entry": direct_long,
        "utad_entry": utad_entry,
        "second_sell_entry": second_sell_entry,
        "third_sell_entry": third_sell_entry,
        "zs_breakdown_short_entry": direct_short,
        "long_entry": long_entry,
        "short_entry": short_entry,
        "new_risk_set": new_risk_set,
    }
    state.current_events = events
    return {
        "date": bar_date,
        "close": float(row["close"]),
        "atr14": row["atr14"],
        "stroke_count": len(state.stroke_prices),
        "zs_active": state.zs_active,
        "zs_zd": state.zs_zd,
        "zs_zg": state.zs_zg,
        "regime": state.regime,
        "wyckoff": state.wyckoff,
        "setup": state.setup,
        "direction": state.direction,
        "trigger": state.trigger,
        "status": state.status.name,
        "entry_price": state.entry_price,
        "sl": state.sl,
        "tp1": state.tp1,
        "tp2": state.tp2,
        "active_risk_ready": state.active_risk_ready,
        "active_trade_closed": state.active_trade_closed,
        **events,
    }


def _run_engine(df: pd.DataFrame, profile: MarketProfile, collect_trace: bool) -> tuple[EngineState, pd.DataFrame]:
    history = _prepare_indicators(df, profile)
    records = history.to_dict("records")
    dates = history.index.to_list()
    state = EngineState()
    trace: list[dict] = []
    for index in range(len(records)):
        row = _process_bar(state, records, dates[index], index, profile)
        if collect_trace:
            trace.append(row)
    return state, pd.DataFrame(trace)


def replay_bars(df: pd.DataFrame, profile: MarketProfile) -> EngineState:
    return _run_engine(df, profile, collect_trace=False)[0]


def scan_history(df: pd.DataFrame, profile: MarketProfile) -> pd.DataFrame:
    """Return a per-bar state trace for static parity and regression testing."""
    return _run_engine(df, profile, collect_trace=True)[1]


def build_scan_result(
    symbol: str,
    df: pd.DataFrame,
    market_profile: MarketProfile,
    state: EngineState,
    name: str = "",
    sector: str = "",
) -> ScanResult:
    latest = df.iloc[-1]
    return ScanResult(
        symbol=symbol,
        market=market_profile.key.upper(),
        signal_date=df.index[-1].date(),
        close=float(latest["close"]),
        status=state.status.name,
        status_rank=int(state.status),
        setup=state.setup,
        regime=state.regime,
        wyckoff=state.wyckoff,
        trigger=state.trigger,
        direction=state.direction,
        zs_zd=_round(state.zs_zd, market_profile.tick_size),
        zs_zg=_round(state.zs_zg, market_profile.tick_size),
        entry_price=_round(state.entry_price, market_profile.tick_size),
        sl=_round(state.sl, market_profile.tick_size),
        tp1=_round(state.tp1, market_profile.tick_size),
        tp2=_round(state.tp2, market_profile.tick_size),
        name=name,
        sector=sector,
        notes="; ".join(state.notes),
        engine_version=ENGINE_VERSION,
    )


def scan_symbol(
    symbol: str,
    df: pd.DataFrame,
    market_profile: MarketProfile,
    name: str = "",
    sector: str = "",
    min_bars: int = 180,
) -> ScanResult:
    canonical = normalize_ohlcv(df)
    valid, errors = validate_ohlcv(canonical, min_bars=min_bars)
    if not valid:
        raise ValueError(f"Invalid OHLCV for {symbol}: {', '.join(errors)}")
    state = replay_bars(canonical, market_profile)
    return build_scan_result(symbol, canonical, market_profile, state, name, sector)
