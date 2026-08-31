from __future__ import annotations

import pandas as pd

from engine.cwp_engine import (
    _bar_parameters,
    _register_breaks,
    _update_second_points,
    _update_spring_utad,
    _update_third_points,
    calculate_trade_levels,
    update_wyckoff_state,
)
from engine.market_profiles import get_market_profile
from engine.models import EngineState, SetupCode, WyckoffState


def _history(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, index=pd.bdate_range("2026-01-01", periods=len(rows)))
    defaults = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000, "atr14": 2.0, "atr_slow": 2.0, "vol_sma": 1_000_000}
    for field, value in defaults.items():
        if field not in frame:
            frame[field] = value
        else:
            frame[field] = frame[field].fillna(value)
    return frame


def test_spring_requires_follow_up_break_of_spring_high_and_bos():
    profile = get_market_profile("sp500", "Long Only")
    history = _history(
        [
            {},
            {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"open": 102.0, "high": 104.0, "low": 100.5, "close": 103.0},
        ]
    )
    state = EngineState(zs_active=True, zs_zd=100.0, zs_zg=110.0, wyc_state=int(WyckoffState.ACCUMULATION))
    parameters = _bar_parameters(history.iloc[1], profile)
    spring_event, _, spring_entry, _ = _update_spring_utad(state, history, 1, parameters, profile, True, False, False)
    assert spring_event and not spring_entry and state.spring_pending
    _, _, spring_entry, _ = _update_spring_utad(state, history, 2, parameters, profile, True, True, False)
    assert spring_entry and not state.spring_pending


def test_wyckoff_requires_climax_then_lower_effort_secondary_test():
    profile = get_market_profile("sp500", "Long Only")
    history = _history(
        [
            {},
            {"open": 101.0, "high": 104.0, "low": 99.5, "close": 103.0, "volume": 1_600_000},
            {"open": 101.0, "high": 102.5, "low": 100.0, "close": 102.0, "volume": 1_000_000},
        ]
    )
    state = EngineState(zs_active=True, zs_zd=100.0, zs_zg=110.0)
    parameters = _bar_parameters(history.iloc[1], profile)
    _, sc_like, _, accumulation_st, _ = update_wyckoff_state(state, history, 1, parameters, profile, False)
    assert sc_like and not accumulation_st
    assert state.wyc_state == int(WyckoffState.ACCUM_WATCH)
    _, _, _, accumulation_st, _ = update_wyckoff_state(state, history, 2, parameters, profile, False)
    assert accumulation_st
    assert state.wyc_state == int(WyckoffState.ACCUMULATION)


def test_second_buy_lifecycle_uses_1b_pullback_and_confirmation_high():
    profile = get_market_profile("sp500", "Long Only")
    history = _history(
        [
            {"open": 109.0, "high": 112.0, "low": 108.0, "close": 111.0},
            {"open": 106.0, "high": 108.0, "low": 95.0, "close": 107.0},
            {"open": 112.0, "high": 114.0, "low": 110.0, "close": 113.0},
        ]
    )
    state = EngineState()
    potential, _, entry, _ = _update_second_points(state, 0, history.iloc[0], profile, False, True, 110.0, 90.0, None, None, False, False)
    assert potential and not entry and state.first_buy_active
    state.micro_swing_high = 112.0
    _, _, entry, _ = _update_second_points(state, 1, history.iloc[1], profile, False, True, 110.0, 90.0, None, 95.0, False, False)
    assert state.second_buy_pending and state.second_buy_confirm_high == 112.0 and not entry
    _, _, entry, _ = _update_second_points(state, 2, history.iloc[2], profile, False, True, 110.0, 90.0, None, None, True, False)
    assert entry and not state.second_buy_pending


def test_break_registers_third_buy_then_retest_enters():
    profile = get_market_profile("sp500", "Long Only")
    history = _history(
        [
            {},
            {"open": 110.0, "high": 112.0, "low": 109.5, "close": 111.0},
            {"open": 110.2, "high": 111.0, "low": 110.2, "close": 110.8},
        ]
    )
    state = EngineState(zs_active=True, zs_zd=100.0, zs_zg=110.0)
    parameters = _bar_parameters(history.iloc[1], profile)
    fresh_bull, fresh_bear, tolerance = _register_breaks(state, history, 1, parameters)
    assert fresh_bull and not fresh_bear and state.bull_break_registered
    entry, _ = _update_third_points(state, 1, history.iloc[1], profile, fresh_bull, False, tolerance, True, False)
    assert state.third_buy_pending and not entry
    entry, _ = _update_third_points(state, 2, history.iloc[2], profile, False, False, tolerance, True, False)
    assert entry and not state.third_buy_pending


def test_spring_risk_uses_structural_low_buffer_and_opposite_zs_target():
    profile = get_market_profile("sp500", "Long Only")
    history = _history([{}, {"open": 104.0, "high": 106.0, "low": 104.0, "close": 105.0}])
    state = EngineState(spring_low=99.0, spring_target=110.0)
    parameters = _bar_parameters(history.iloc[1], profile)
    created = calculate_trade_levels(state, history, 1, parameters, profile, True, False, int(SetupCode.SPRING))
    assert created
    assert abs(float(state.sl) - 98.4) < 1e-12
    assert state.tp1 == 110.0
    assert abs(float(state.tp2) - 124.8) < 1e-12
