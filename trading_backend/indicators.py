import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series):
    ema12 = ema(series, 12)
    ema26 = ema(series, 26)
    macd_line = ema12 - ema26
    signal_line = ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    high_low = high - low
    high_close = (high - close.shift()).abs()
    low_close = (low - close.shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    average_true_range = true_range.rolling(period).mean()

    plus_di = 100 * plus_dm.rolling(period).mean() / average_true_range
    minus_di = 100 * minus_dm.rolling(period).mean() / average_true_range
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di)) * 100
    dx = dx.mask(dx.isin([float("inf"), -float("inf")]))
    return dx.rolling(period).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    enriched = df.copy()
    enriched["ema20"] = ema(enriched["close"], 20)
    enriched["ema50"] = ema(enriched["close"], 50)
    enriched["rsi14"] = rsi(enriched["close"], 14)
    enriched["macd"], enriched["macd_signal"], enriched["macd_hist"] = macd(
        enriched["close"]
    )
    enriched["atr14"] = atr(enriched, 14)
    enriched["atr_pct"] = enriched["atr14"] / enriched["close"]
    enriched["adx14"] = adx(enriched, 14)
    return enriched
