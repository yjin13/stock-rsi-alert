import os
import time
import json
import datetime
import requests
import pandas as pd
import yfinance as yf

# 🚨 [테스트 스위치] True로 두면 30분마다 상위 10개 종목 RSI를 무조건 알림합니다.
TEST_MODE = True

# GitHub Secrets에서 텔레그램 토큰/채팅ID 불러오기
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
        # 밤샘 거래 특성을 고려하여 오전 12시 이전은 '전날 밤 미국장 세션'으로 통합 계산
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

    def send_telegram_alert(self, name, ticker, rsi_val, close_p):
        url_link = f"https://finance.yahoo.com/quote/{ticker}"
        price_str = f"${close_p:,.2f}"
        self.state["signal_found"] = True
        self.save_state()

        message = (
            f"🚨 <b>🇺🇸 [미국장 4H RSI 과대낙폭 감지]</b>\n\n"
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

    def send_daily_summary(self, date_str):
        self.state["summary_sent"] = True
        self.save_state()

        message = (
            f"📊 <b>🇺🇸 [미국장 일일 마감 보고]</b>\n\n"
            f"• 기준 날짜: {date_str} (오버나이트 세션)\n"
            f"• 스캔 결과: 밤사이 미국장 마감(프리~애프터장 포함)까지 <b>4시간봉 RSI 30 이하</b>인 과대낙폭 종목이 <b>발견되지 않았습니다.</b>\n\n"
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
        return {
            "AAPL": "애플", "NVDA": "엔비디아", "TSLA": "테슬라", "MSFT": "마이크로소프트",
            "AMZN": "아마존", "GOOGL": "알파벳(구글)", "META": "메타", "AMD": "AMD",
            "NFLX": "넷플릭스", "AVGO": "브로드컴", "INTC": "인텔", "QCOM": "퀄컴",
            "ARM": "ARM 홀딩스", "PLTR": "팔란티어", "SMCI": "슈퍼마이크로", "MU": "마이크론",
            "TSM": "TSMC", "ASML": "ASML", "COIN": "코인베이스", "SOFI": "소파이",
            "MSTR": "마이크로스트래티지", "LLY": "일라이릴리", "UBER": "우버", "DIS": "디즈니",
            "CRWD": "크라우드스트라이크", "SNOW": "스노우플레이크", "PANW": "팔로알토",
            "V": "비자", "MA": "마스터카드", "JPM": "JP모건", "JNJ": "존슨앤드존슨",
            "WMT": "월마트", "COST": "코스트코", "TXN": "텍사스인스트루먼트"
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
    
    def send_test_summary_alert(self, results):
        """[테스트 전용] 상위 10개 종목의 현재 4H RSI 요약 메시지 발송"""
        text_lines = []
        for i, (name, ticker, rsi, price) in enumerate(results, 1):
            text_lines.append(f"{i}. <b>{name}</b> (<code>{ticker}</code>) | RSI: <b>{rsi:.2f}</b> | ${price:,.2f}")
        
        message = (
            "🧪 <b>🇺🇸 [미국장 상위 10개 종목 4H RSI 테스트]</b>\n\n"
            + "\n".join(text_lines)
            + "\n\n<i>(🛠️ TEST_MODE=True 작동 중 · 30 이하 조건 무시)</i>"
        )
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(self.api_url, data=payload)
        print("  └─> [미국장 상위 10개 테스트 알림 전송 완료]")

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        
        print(f" [🇺🇸 미국장 스캐너 실행] KST 시간: {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (UTC {utc_hour}시)")

        # [A] 테스트 모드가 켜진 경우: 시간/RSI 조건 없이 상위 10개 즉시 알림
        if TEST_MODE:
            print("\n [🧪 미국장 TEST_MODE 활성화: 상위 10개 종목 RSI 스캔 중...]")
            us_stocks = self.get_us_top100()
            top10_items = list(us_stocks.items())[:10]
            
            test_results = []
            for ticker, name in top10_items:
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi:
                        test_results.append((name, ticker, rsi, close_p))
                    time.sleep(0.1)
                except Exception:
                    continue
            
            if test_results:
                self.send_test_summary_alert(test_results)
            return  # 테스트 실행 완료 후 종료

        # [B] 일반 모드 (TEST_MODE = False일 때 본래 로직 작동)
        # 한국 시간 17:00 ~ 익일 10:00 (UTC 08시~23시 및 0시~2시) 작동
        if 8 <= utc_hour <= 23 or utc_hour in [0, 1, 2]:
            us_stocks = self.get_us_top100()
            print(f">> 미국 주도주 {len(us_stocks)}개 종목 분석 중...")
            for ticker, name in us_stocks.items():
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi and rsi <= 30.0:
                        self.send_telegram_alert(name, ticker, rsi, close_p)
                    time.sleep(0.3)
                except Exception:
                    continue
            
            # 아침 9시~11시 (UTC 0시, 1시, 2시) 서머타임/동절기 마감 보고 체크
            if utc_hour in [0, 1, 2] and not self.state["summary_sent"]:
                if not self.state["signal_found"]:
                    self.send_daily_summary(date_str)
                else:
                    self.state["summary_sent"] = True
                    self.save_state()

if __name__ == "__main__":
    bot = USAmericaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()