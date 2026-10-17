import json
import numpy as np
import pandas as pd


def wilder_rsi(close_series, period=14):
    """Wilder 평활(RMA, alpha=1/period) RSI — TradingView/HTS 기본 방식. 마지막 값만 반환."""
    delta = close_series.diff(1)
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)

    avg_up = up.ewm(alpha=1 / period, adjust=False).mean()
    avg_down = down.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_up / avg_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_down != 0, 100.0)  # 하락분이 없으면 RSI 100

    if pd.isna(rsi.iloc[-1]):
        return None
    return float(rsi.iloc[-1])


def resample_4h_close(df_1m, origin):
    """분봉 종가를 origin 기준 4시간봉 종가로 묶는다(봉 시작 시각이 인덱스)."""
    return df_1m["close"].resample("4h", origin=origin, label="left", closed="left").last().dropna()


def split_complete(closes, now, session_close):
    """봉 종료 = min(시작+4h, 당일 장 마감). 종료가 지난 봉은 '완성', 아니면 '진행 중'."""
    done = np.array([
        min(ts + pd.Timedelta(hours=4), pd.Timestamp.combine(ts.date(), session_close)) <= now
        for ts in closes.index
    ], dtype=bool)
    return closes[done], closes[~done]


class BarCache:
    """종목별 '완성된' 4시간봉 종가 캐시(JSON). 워크플로가 커밋해 실행 간에 유지한다."""

    def __init__(self, path, keep_bars=200, keep_days=14):
        self.path = path
        self.keep_bars = keep_bars
        self.keep_days = keep_days
        self.dirty = False
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def entry(self, key):
        return self.data.get(key) or {}

    def closes(self, key):
        bars = self.entry(key).get("bars") or []
        if not bars:
            return pd.Series(dtype=float)
        return pd.Series([b[1] for b in bars], index=pd.to_datetime([b[0] for b in bars]), dtype=float)

    def update(self, key, closes, today_str, **extra):
        closes = closes.iloc[-self.keep_bars:]
        new = {
            "seen": today_str,
            **extra,
            "bars": [[ts.strftime("%Y-%m-%dT%H:%M"), float(c)] for ts, c in closes.items()],
        }
        if self.data.get(key) != new:
            self.data[key] = new
            self.dirty = True

    def prune(self, today):
        cutoff = (today - pd.Timedelta(days=self.keep_days)).strftime("%Y-%m-%d")
        for key in [k for k, e in self.data.items() if e.get("seen", "") < cutoff]:
            del self.data[key]
            self.dirty = True

    def save(self):
        if not self.dirty:
            return
        # 종목당 한 줄로 저장해 커밋 diff를 작게 유지
        lines = [f"{json.dumps(k)}: {json.dumps(e, separators=(',', ':'), ensure_ascii=False)}" for k, e in sorted(self.data.items())]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{\n" + ",\n".join(lines) + "\n}\n")
        self.dirty = False
