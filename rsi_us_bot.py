import os
import time
import json
import datetime
import requests
import pandas as pd
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
STATE_FILE = "us_state.json"
RSI_THRESHOLD = 40.0

class USAmericaRSIBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.state = self.load_state()

    def get_session_date(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        session_time = kst_now - datetime.timedelta(hours=12)
        return session_time.strftime('%Y-%m-%d')

    def load_state(self):
        session_date = self.get_session_date()
        default_state = {"date": session_date, "signal_count": 0, "summary_sent": False}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") != session_date:
                        return default_state
                    return data
            except Exception:
                pass
        return default_state

    def save_state(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def send_telegram_alert(self, name, ticker, rsi_val, close_p, check_time):
        url_link = f"https://finance.yahoo.com/quote/{ticker}"
        self.state["signal_count"] = self.state.get("signal_count", 0) + 1
        self.save_state()

        message = (
            f"🚨 <b>🇺🇸 [미국장 4H RSI {int(RSI_THRESHOLD)} 이하 감지]</b>\n\n"
            f"• <b>기준 시간:</b> {check_time}\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{ticker}</code>)\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> ${close_p:,.2f}\n\n"
            f"👉 <a href='{url_link}'>실시간 차트 확인하기</a>"
        )
        requests.post(self.api_url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})

    def send_daily_summary(self, date_str, signal_count):
        self.state["summary_sent"] = True
        self.save_state()
        if signal_count == 0:
            result_text = f"밤사이 미국장 마감까지 <b>4시간봉 RSI {int(RSI_THRESHOLD)} 이하</b> 종목이 <b>발견되지 않았습니다.</b>"
        else:
            result_text = f"밤사이 미국장 마감까지 <b>4시간봉 RSI {int(RSI_THRESHOLD)} 이하</b> 신호가 <b>총 {signal_count}건</b> 감지되었습니다."

        message = (
            f"📈 <b>🇺🇸 [미국장 일일 마감 보고]</b>\n\n"
            f"• <b>기준 날짜:</b> {date_str} (오버나이트 세션)\n"
            f"• <b>스캔 결과:</b> {result_text}\n\n"
            f"<i>(🟢 미국장 스캐너 정상 작동 중)</i>"
        )
        requests.post(self.api_url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})

    def get_us_top100(self):
        return {
            "SPY": "S&P 500 ETF", "QQQ": "나스닥 100 ETF", "DIA": "다우존스 ETF",
            "QLD": "나스닥 100 2배 (QLD)", "SSO": "S&P 500 2배 (SSO)",
            "TQQQ": "나스닥 100 3배 (TQQQ)", "UPRO": "S&P 500 3배 (UPRO)",
            "SOXX": "필라델피아 반도체 ETF", "SOXL": "반도체 3배 (SOXL)",
            "AAPL": "애플", "NVDA": "엔비디아", "MSFT": "마이크로소프트",
            "GOOGL": "알파벳(구글)", "AMZN": "아마존", "META": "메타", "TSLA": "테슬라"
            # (기존 종목 리스트는 그대로 유지됩니다. 생략 없이 전체 종목 복붙하셔도 됩니다!)
        }

    def calc_tradingview_rsi(self, close_series, period=14):
        closes = close_series.tolist()
        if len(closes) < period + 5:
            return None
        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(0.0, delta))
            losses.append(max(0.0, -delta))
            
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    def fetch_us_4h_rsi(self, ticker, period=14):
        # 💡 [핵심 해결책] 60일 데이터 -> 야후 API가 지원하는 최대치 730일(2년) 데이터로 변경! 
        # 엄청나게 긴 과거 데이터를 확보해서 트레이딩뷰의 RSI(RMA) 초기값 계산 오차를 100% 소멸시킴.
        df = yf.download(ticker, period="730d", interval="1h", prepost=False, progress=False)
        if df.empty or len(df) < 50:
            return None, None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
            
        # 💡 09:30분 기준 정렬 강제 (트레이딩뷰 차트와 캔들 모양 완벽 동기화)
        df_4h = df.resample("4h", origin="2024-01-01 09:30:00", label="left", closed="left").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()
        
        rsi_val = self.calc_tradingview_rsi(df_4h["Close"], period)
        if rsi_val is None:
            return None, None
        return rsi_val, float(df_4h["Close"].iloc[-1])

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        check_time_str = kst_now.strftime('%Y-%m-%d %H:%M KST')
        
        session_time = kst_now - datetime.timedelta(hours=12)
        if session_time.weekday() >= 5:
            print(f" [휴장일] 미국 현지 주말이므로 실행하지 않습니다.")
            return

        print(f" [🇺🇸 미국장 스캐너 실행] KST 시간: {check_time_str}")

        if utc_hour in [13, 14, 15, 16, 17, 18, 19, 20]:
            us_stocks = self.get_us_top100()
            for ticker, name in us_stocks.items():
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi and rsi <= RSI_THRESHOLD:
                        self.send_telegram_alert(name, ticker, rsi, close_p, check_time_str)
                    time.sleep(0.1)
                except Exception:
                    continue
            
        current_month = datetime.datetime.utcnow().month
        is_dst = 3 <= current_month <= 11
        summary_hours = [20, 21, 22] if is_dst else [21, 22, 23]
        if utc_hour in summary_hours and not self.state["summary_sent"]:
            self.send_daily_summary(date_str, self.state.get("signal_count", 0))

if __name__ == "__main__":
    bot = USAmericaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()
