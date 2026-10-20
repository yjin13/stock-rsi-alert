import pandas as pd
from lib.rsi_common import resample_4h_close, split_complete

US_BAR_ORIGIN = "2024-01-01 09:30:00"  # rsi_us_bot.BAR_ORIGIN과 같은 4시간봉 경계(현지시각)


def fetch_us_4h_seed(ticker, now, session_close):
    """KIS 해외 분봉이 약 1개월치만 제공돼 부족한 과거 이력을 yfinance 60분봉(최대 약 2년)으로 채운다.

    정규장 60분봉(09:30, 10:30, ... 15:30)을 KIS와 같은 경계(09:30~13:30, 13:30~16:00)의
    4시간봉으로 묶어 '완성된 봉'만 반환한다. now는 미국 동부 현지 시각(naive).
    """
    import yfinance as yf  # 시드할 때만 필요하므로 지연 임포트(미설치여도 KIS 경로는 동작)

    df = yf.Ticker(ticker).history(period="730d", interval="60m", prepost=False, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError("yfinance 응답이 비어 있습니다")
    df = df.rename(columns=str.lower)
    df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    complete, _ = split_complete(resample_4h_close(df, US_BAR_ORIGIN), now, session_close)
    return complete
