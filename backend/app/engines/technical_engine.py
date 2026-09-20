"""Technical indicator engine (section 7).

Only the indicators the spec calls useful for 1-4 week MTF analysis: EMA20/
50/200, RSI14, ATR14, ADX14, VWAP (session-approx from daily data), recent
20d high/low, support/resistance, breakout/pullback status, trend structure.

All functions are pure: list[Candle] in, plain floats/labels out. No I/O.
"""

import numpy as np
import pandas as pd

from app.data.internal_models import Candle


def _to_frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [c.trade_date for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_s = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_s.replace(0, np.nan)

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def vwap_approx(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Approximate rolling VWAP from daily OHLCV (true intraday VWAP needs
    tick/minute data, which the daily-candle pipeline doesn't carry)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical_price * df["volume"]
    return pv.rolling(window).sum() / df["volume"].rolling(window).sum()


def _trend_structure(last_close: float, e20: float | None, e50: float | None, e200: float | None) -> str:
    if e20 is None or e50 is None or e200 is None:
        return "INSUFFICIENT_DATA"
    if last_close > e20 > e50 > e200:
        return "STRONG_UPTREND"
    if last_close > e50 > e200:
        return "UPTREND"
    if last_close < e20 < e50 < e200:
        return "STRONG_DOWNTREND"
    if last_close < e50 < e200:
        return "DOWNTREND"
    return "RANGE_BOUND"


def _breakout_status(last_close: float, recent_high_20d: float | None, avg_close_10d: float) -> str:
    if recent_high_20d is None:
        return "INSUFFICIENT_DATA"
    if last_close >= recent_high_20d * 0.999:
        return "BREAKOUT"
    if last_close >= recent_high_20d * 0.97:
        return "APPROACHING_BREAKOUT"
    return "NO_BREAKOUT"


def _pullback_status(last_close: float, e20: float | None, e50: float | None, trend: str) -> str:
    if e20 is None or e50 is None:
        return "INSUFFICIENT_DATA"
    if trend in ("STRONG_UPTREND", "UPTREND"):
        if e50 <= last_close <= e20 * 1.01:
            return "PULLBACK_TO_SUPPORT"
        if last_close < e50:
            return "DEEP_PULLBACK"
        return "NO_PULLBACK"
    return "NOT_APPLICABLE"


class TechnicalResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def compute_technical_metrics(candles: list[Candle]) -> TechnicalResult:
    """Returns a TechnicalResult with attributes matching schemas.stock.TechnicalData.

    If fewer than 20 candles are available, returns a result with everything
    set to None / INSUFFICIENT_DATA rather than fabricating numbers.
    """
    if len(candles) < 20:
        return TechnicalResult(
            ema_20=None, ema_50=None, ema_200=None, rsi_14=None, atr_14=None,
            adx_14=None, vwap=None, recent_high_20d=None, recent_low_20d=None,
            support_level=None, resistance_level=None,
            trend_structure="INSUFFICIENT_DATA", breakout_status="INSUFFICIENT_DATA",
            pullback_status="INSUFFICIENT_DATA",
        )

    df = _to_frame(candles)
    close = df["close"]

    e20 = ema(close, 20)
    e50 = ema(close, 50) if len(df) >= 50 else pd.Series([np.nan] * len(df))
    e200 = ema(close, 200) if len(df) >= 200 else pd.Series([np.nan] * len(df))
    rsi_s = rsi(close, 14)
    atr_s = atr(df, 14)
    adx_s = adx(df, 14)
    vwap_s = vwap_approx(df, 20)

    last_close = float(close.iloc[-1])
    recent_high_20d = float(df["high"].tail(20).max())
    recent_low_20d = float(df["low"].tail(20).min())
    avg_close_10d = float(close.tail(10).mean())

    def last_or_none(s: pd.Series) -> float | None:
        v = s.iloc[-1]
        return None if pd.isna(v) else float(v)

    e20_v, e50_v, e200_v = last_or_none(e20), last_or_none(e50), last_or_none(e200)

    trend = _trend_structure(last_close, e20_v, e50_v, e200_v)
    breakout = _breakout_status(last_close, recent_high_20d, avg_close_10d)
    pullback = _pullback_status(last_close, e20_v, e50_v, trend)

    support = float(min(recent_low_20d, e50_v if e50_v else recent_low_20d))
    resistance = float(recent_high_20d)

    return TechnicalResult(
        ema_20=e20_v,
        ema_50=e50_v,
        ema_200=e200_v,
        rsi_14=last_or_none(rsi_s),
        atr_14=last_or_none(atr_s),
        adx_14=last_or_none(adx_s),
        vwap=last_or_none(vwap_s),
        recent_high_20d=recent_high_20d,
        recent_low_20d=recent_low_20d,
        support_level=support,
        resistance_level=resistance,
        trend_structure=trend,
        breakout_status=breakout,
        pullback_status=pullback,
    )
