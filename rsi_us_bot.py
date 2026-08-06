import os
import re
import time
import json
import datetime
import requests
import pandas as pd
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
STATE_FILE = "us_state.json"

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
        default_state = {
            "date": session_date,
            "signal_found": False,
            "summary_sent": False
        }
        
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
        except Exception as e:
            print(f"미국장 상태 저장 실패: {e}")

    def send_telegram_alert(self, name, ticker, rsi_val, close_p, check_time):
        url_link = f"https://finance.yahoo.com/quote/{ticker}"
        price_str = f"${close_p:,.2f}"
        self.state["signal_found"] = True
        self.save_state()

        message = (
            f"🚨 <b>🇺🇸 [미국장 4H RSI 과대낙폭 감지]</b>\n\n"
            f"• <b>기준 시간:</b> {check_time}\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{ticker}</code>)\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> {price_str}\n\n"
            f"👉 <a href='{url_link}'>실시간 차트 확인하기</a>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(self.api_url, data=payload)

    def send_top30_summary(self, results, check_time):
        """💡 매 시간 스케줄러 실행 시 상위 30개 종목의 4H RSI 및 현재가 정기 보고"""
        text_lines = []
        for i, (name, ticker, rsi, price) in enumerate(results[:30], 1):
            text_lines.append(f"{i}. <b>{name}</b> (<code>{ticker}</code>) | RSI: <b>{rsi:.2f}</b> | ${price:,.2f}")
        
        message = (
            f"📊 <b>🇺🇸 [미국장 상위 30개 종목 4H RSI 정기 리포트]</b>\n"
            f"• <b>기준 시간:</b> {check_time}\n\n"
            + "\n".join(text_lines)
            + "\n\n<i>(🟢 스케줄러 정상 작동 확인용 자동 발송)</i>"
        )
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(self.api_url, data=payload)
        print("  └─> [미국장 상위 30개 정기 리포트 전송 완료]")

    def send_daily_summary(self, date_str):
        self.state["summary_sent"] = True
        self.save_state()

        message = (
            f"📈 <b>🇺🇸 [미국장 일일 마감 보고]</b>\n\n"
            f"• <b>기준 날짜:</b> {date_str} (오버나이트 세션)\n"
            f"• <b>스캔 결과:</b> 밤사이 미국장 마감(프리~애프터장 포함)까지 <b>4시간봉 RSI 30 이하</b>인 과대낙폭 종목이 <b>발견되지 않았습니다.</b>\n\n"
            f"<i>(🟢 미국장 스캐너 정상 작동 중 · 다음 장에서 뵙겠습니다)</i>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(self.api_url, data=payload)
        print("  └─> [미국장 일일 마감 보고 전송 완료]")

    def get_us_top100(self):
        """
        💡 지수/섹터 레버리지 + 기술주/소비재/금융/헬스케어 등 미국 시총 최상위 블루칩
        🚨 단일 종목 레버리지 ETF 및 인버스 ETF 원천 배제
        """
        return {
            # --- [핵심 지수 및 섹터 레버리지 ETF (1~3배)] ---
            "SPY": "S&P 500 ETF",
            "QQQ": "나스닥 100 ETF",
            "DIA": "다우존스 ETF",
            "QLD": "나스닥 100 2배 (QLD)",
            "SSO": "S&P 500 2배 (SSO)",
            "TQQQ": "나스닥 100 3배 (TQQQ)",
            "UPRO": "S&P 500 3배 (UPRO)",
            "SOXX": "필라델피아 반도체 ETF",
            "SOXL": "반도체 3배 (SOXL)",
            "SMH": "반도체 섹터 (SMH)",
            "USD": "반도체 2배 (USD)",
            "XLK": "기술주 섹터 (XLK)",
            "TLT": "미국 20년물 국채 ETF",
            "TMF": "미국 20년물 국채 3배 (TMF)",
            
            # --- [시가총액 상위 7대 빅테크 및 성장주] ---
            "AAPL": "애플",
            "NVDA": "엔비디아",
            "MSFT": "마이크로소프트",
            "GOOGL": "알파벳(구글)",
            "AMZN": "아마존",
            "META": "메타",
            "TSLA": "테슬라",
            
            # --- [반도체 & 핵심 IT 주도주] ---
            "AVGO": "브로드컴",
            "TSM": "TSMC",
            "AMD": "AMD",
            "ASML": "ASML",
            "QCOM": "퀄컴",
            "TXN": "텍사스 인스트루먼트",
            "MU": "마이크론",
            "INTC": "인텔",
            "ARM": "ARM 홀딩스",
            "SMCI": "슈퍼마이크로",
            "PLTR": "팔란티어",
            "CRWD": "크라우드스트라이크",
            "SNOW": "스노우플레이크",
            "PANW": "팔로알토",
            
            # --- [소비재 & 유통 & 엔터 시총 상위주 (나이키 포함)] ---
            "NKE": "나이키",
            "WMT": "월마트",
            "COST": "코스트코",
            "HD": "홈디포",
            "MCD": "맥도날드",
            "SBUX": "스타벅스",
            "DIS": "디즈니",
            "NFLX": "넷플릭스",
            "UBER": "우버",
            
            # --- [필수소비재 & 음료 주도주] ---
            "PG": "프록터앤드갬블(P&G)",
            "KO": "코카콜라",
            "PEP": "펩시코",
            
            # --- [금융 & 결제 시총 최상위 블루칩] ---
            "BRK-B": "버크셔 해서웨이",
            "JPM": "JP모건 체이스",
            "BAC": "뱅크오브아메리카",
            "V": "비자",
            "MA": "마스터카드",
            "SOFI": "소파이",
            "COIN": "코인베이스",
            "MSTR": "마이크로스트래티지",
            
            # --- [헬스케어 & 제약 시총 상위주] ---
            "LLY": "일라이릴리",
            "UNH": "유나이티드헬스",
            "JNJ": "존슨앤드존슨",
            "MRK": "머크",
            "ABBV": "애브비",
            
            # --- [에너지 & 산업재 주도주] ---
            "XOM": "엑슨모빌",
            "CVX": "쉐브론",
            "GE": "제너럴 일렉트릭",
            "CAT": "캐터필러"
        }

    def fetch_us_4h_rsi(self, ticker, period=14):
        df = yf.download(ticker, period="1mo", interval="1h", prepost=True, progress=False)
        if df.empty or len(df) < 30:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df_4h = df.resample("4h", label="left", closed="left").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna()
        
        delta = df_4h["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        df_4h["RSI"] = 100 - (100 / (1 + rs))
        return float(df_4h["RSI"].iloc[-1]), float(df_4h["Close"].iloc[-1])

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        check_time_str = kst_now.strftime('%Y-%m-%d %H:%M KST')
        
        print(f" [🇺🇸 미국장 스캐너 실행] KST 시간: {check_time_str} (UTC {utc_hour}시)")

        # 🟢 미국장 거래 시간대에 실행 시: 상위 30개 정기 리포트 발송 + 30 이하 과대낙폭 감시
        if 8 <= utc_hour <= 23 or utc_hour in [0, 1, 2]:
            us_stocks = self.get_us_top100()
            top30_results = []
            
            for ticker, name in us_stocks.items():
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi:
                        # 상위 30개 종목 리스트 수집
                        if len(top30_results) < 30:
                            top30_results.append((name, ticker, rsi, close_p))
                        
                        # 4H RSI 30 이하 시 즉시 과대낙폭 경보 발송
                        if rsi <= 30.0:
                            self.send_telegram_alert(name, ticker, rsi, close_p, check_time_str)
                    time.sleep(0.1)
                except Exception:
                    continue
            
            # 상위 30개 종목 정리 리포트 전송
            if top30_results:
                self.send_top30_summary(top30_results, check_time_str)
            
            # 장 마감 시간 보고
            if utc_hour in [0, 1, 2] and not self.state["summary_sent"]:
                if not self.state["signal_found"]:
                    self.send_daily_summary(date_str)
                else:
                    self.state["summary_sent"] = True
                    self.save_state()

if __name__ == "__main__":
    bot = USAmericaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()