import os
import time
import json
import datetime
import requests
import pandas as pd
import yfinance as yf
import holidays

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
STATE_FILE = "us_state.json"
RSI_THRESHOLD = 30.0  # 🎯 원하는 RSI 수치

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
        default_state = {"date": session_date, "signal_count": 0, "summary_sent": False, "alerted": []}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") != session_date:
                        return default_state
                    if "alerted" not in data:
                        data["alerted"] = []
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

    def get_us_target_stocks(self):
        base_stocks = {
            "SPY": "S&P 500 ETF", "QQQ": "나스닥 100 ETF", "DIA": "다우존스 ETF",
            "TQQQ": "나스닥 3배", "SQQQ": "나스닥 인버스 3배", "QLD": "나스닥 2배",
            "UPRO": "S&P500 3배", "SOXX": "반도체 ETF", "SOXL": "반도체 3배", 
            "SOXS": "반도체 인버스 3배", "USD": "반도체 2배", "TLT": "20년물 국채", 
            "TMF": "국채 3배", "TSLL": "테슬라 1.5배", "CONL": "코인베이스 2배",
            "NVDL": "엔비디아 2배", "FNGU": "빅테크 3배", "TZA": "중소형주 인버스 3배",
            "BOIL": "천연가스 2배", "SCHD": "미국 배당성장 ETF",
            "AAPL": "애플", "NVDA": "엔비디아", "MSFT": "마이크로소프트",
            "GOOGL": "알파벳(구글)", "AMZN": "아마존", "META": "메타", "TSLA": "테슬라",
            "AVGO": "브로드컴", "TSM": "TSMC", "AMD": "AMD", "ASML": "ASML",
            "QCOM": "퀄컴", "TXN": "텍사스 인스트루먼트", "MU": "마이크론",
            "INTC": "인텔", "ARM": "ARM 홀딩스", "SMCI": "슈퍼마이크로",
            "PLTR": "팔란티어", "CRWD": "크라우드스트라이크", "SNOW": "스노우플레이크",
            "PANW": "팔로알토", "NOW": "서비스나우", "ADBE": "어도비",
            "COIN": "코인베이스", "MSTR": "마이크로스트래티지", "HOOD": "로빈후드",
            "UBER": "우버", "NFLX": "넷플릭스", "CRM": "세일즈포스", 
            "DDOG": "데이터독", "NET": "클라우드플레어",
            "JPM": "JP모건", "V": "비자", "BRK-B": "버크셔 해서웨이", 
            "LLY": "일라이릴리", "UNH": "유나이티드헬스", "NVO": "노보 노디스크",
            "JNJ": "존슨앤드존슨", "PEP": "펩시코", "MCD": "맥도날드", "ABBV": "애브비",
            "WMT": "월마트", "COST": "코스트코", "PG": "프록터앤드갬블", "KO": "코카콜라",
            "CAT": "캐터필러", "GE": "제너럴일렉트릭", "XOM": "엑슨모빌", 
            "CVX": "쉐브론", "BA": "보잉"
        }

        my_favorites = {
            "GME": "게임스탑",
            "AMC": "AMC 엔터테인먼트",
            "RDDT": "레딧",
            "DJT": "트럼프 미디어"
        }
        
        base_stocks.update(my_favorites)
        return base_stocks

    def calc_tradingview_rsi(self, close_series, period=14):
        # 💡 국내 HTS(키움증권 등) 전용 EMA 방식 계산
        delta = close_series.diff(1)
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        
        roll_up = up.ewm(span=period, adjust=False).mean()
        roll_down = down.ewm(span=period, adjust=False).mean()
        
        rs = roll_up / roll_down
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        if pd.isna(rsi.iloc[-1]):
            return None
        return float(rsi.iloc[-1])

    def fetch_us_4h_rsi(self, ticker, period=14):
        yf_ticker = ticker.replace(".", "-") 
        
        df = yf.download(yf_ticker, period="730d", interval="1h", prepost=False, progress=False)
        if df.empty or len(df) < 50:
            return None, None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
            
        df_4h = df.resample("4h", origin="2024-01-01 09:30:00", label="left", closed="left").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()
        
        # 🔥 야후 1h 딜레이 무시하고 '실시간 1분봉 가격' 강제 주입
        try:
            live_data = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
            if not live_data.empty:
                if isinstance(live_data.columns, pd.MultiIndex):
                    live_data.columns = live_data.columns.get_level_values(0)
                live_price = float(live_data["Close"].iloc[-1])
                df_4h.iloc[-1, df_4h.columns.get_loc("Close")] = live_price
        except Exception:
            pass

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
        nyse_holidays = holidays.NYSE()
        
        if session_time.weekday() >= 5 or session_time.date() in nyse_holidays:
            print(f" [휴장일] 미국 현지 주말 또는 공휴일이므로 스캐너를 실행하지 않습니다. ({check_time_str})")
            return

        print(f" [🇺🇸 미국장 스캐너 실행] KST 시간: {check_time_str}")

        # 💡 겨울철 1시간 누락을 막기 위한 '21' 시간대 추가
        if utc_hour in [13, 14, 15, 16, 17, 18, 19, 20, 21]:
            us_stocks = self.get_us_target_stocks()
            for ticker, name in us_stocks.items():
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi and rsi <= RSI_THRESHOLD and ticker not in self.state.get("alerted", []):
                        self.send_telegram_alert(name, ticker, rsi, close_p, check_time_str)
                        self.state["alerted"].append(ticker)
                        self.save_state()
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