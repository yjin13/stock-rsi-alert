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

    def check_telegram_test_command(self):
        """
        텔레그램 봇으로 최근(1시간 이내) 수신된 메시지 중 '/test' 또는 '/test30' 등의 명령어가 있는지 검사
        반환값: (실행여부 True/False, 요청 종목 수 int -> 10~100개 제한)
        """
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates?limit=5"
            res = requests.get(url, timeout=5).json()
            if res.get("ok") and res.get("result"):
                for update in res["result"]:
                    msg = update.get("message", {}).get("text", "").strip()
                    msg_time = update.get("message", {}).get("date", 0)
                    
                    # 최근 1시간(3600초) 이내 메시지만 검사
                    if (time.time() - msg_time) < 3600:
                        match = re.search(r"^/test\s*(\d*)", msg.lower())
                        if match:
                            num_str = match.group(1)
                            if num_str.isdigit():
                                count = int(num_str)
                                # 최소 10개 ~ 최대 100개 사이로 안전 제한
                                count = max(10, min(100, count))
                                return True, count
                            else:
                                return True, 10
        except Exception:
            pass
        return False, 10

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

    def send_test_summary_alert(self, results):
        """[테스트 전용] 요청된 수량만큼의 4H RSI 요약 메시지 발송 (30개 단위 분할 전송)"""
        text_lines = []
        for i, (name, ticker, rsi, price) in enumerate(results, 1):
            text_lines.append(f"{i}. <b>{name}</b> (<code>{ticker}</code>) | RSI: <b>{rsi:.2f}</b> | ${price:,.2f}")
        
        chunk_size = 30
        for i in range(0, len(text_lines), chunk_size):
            chunk = text_lines[i:i + chunk_size]
            page_info = f" ({i//chunk_size + 1}/{(len(text_lines)-1)//chunk_size + 1})" if len(text_lines) > chunk_size else ""
            
            message = (
                f"🧪 <b>🇺🇸 [미국장 상위 {len(results)}개 종목 4H RSI 테스트 리포트]{page_info}</b>\n\n"
                + "\n".join(chunk)
                + "\n\n<i>(🛠️ 텔레그램 '/test' 명령어 감지로 발송되었습니다)</i>"
            )
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            requests.post(self.api_url, data=payload)
            time.sleep(0.3)
        print(f"  └─> [미국장 상위 {len(results)}개 테스트 리포트 전송 완료]")

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

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        
        print(f" [🇺🇸 미국장 스캐너 실행] KST 시간: {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (UTC {utc_hour}시)")

        # 🧪 [1. 텔레그램 '/testN' 명령어 감지 (10~100개)]
        cmd_found, test_count = self.check_telegram_test_command()
        if cmd_found:
            print(f"\n [🧪 미국장 텔레그램 '/test' 감지: 상위 {test_count}개 종목 RSI 요약 발송 중...]")
            us_stocks = self.get_us_top100()
            target_items = list(us_stocks.items())[:test_count]
            
            test_results = []
            for ticker, name in target_items:
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi:
                        test_results.append((name, ticker, rsi, close_p))
                    time.sleep(0.1)
                except Exception:
                    continue
            if test_results:
                self.send_test_summary_alert(test_results)

        # 🟢 [2. 일반 실전 감시 모드] 30 이하 과대낙폭 종목 스캔 및 마감 보고 체크
        if 8 <= utc_hour <= 23 or utc_hour in [0, 1, 2]:
            us_stocks = self.get_us_top100()
            for ticker, name in us_stocks.items():
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi and rsi <= 30.0:
                        self.send_telegram_alert(name, ticker, rsi, close_p)
                    time.sleep(0.1)
                except Exception:
                    continue
            
            if utc_hour in [0, 1, 2] and not self.state["summary_sent"]:
                if not self.state["signal_found"]:
                    self.send_daily_summary(date_str)
                else:
                    self.state["summary_sent"] = True
                    self.save_state()

if __name__ == "__main__":
    bot = USAmericaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()