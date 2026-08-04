import os
import re
import time
import json
import datetime
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import yfinance as yf

# 1) GitHub Secrets에서 텔레그램 토큰/채팅ID 불러오기
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")

STATE_FILE = "daily_summary_state.json"

class DualMarketRSIBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.state = self.load_state()

    def load_state(self):
        """오늘 날짜의 시장별 시그널 감지 및 마감 보고 여부 상태 관리"""
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        today_str = kst_now.strftime('%Y-%m-%d')
        
        default_state = {
            "date": today_str,
            "kr_signal_found": False,
            "kr_summary_sent": False,
            "us_signal_found": False,
            "us_summary_sent": False
        }
        
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") == today_str:
                        return data
            except Exception:
                pass
        return default_state

    def save_state(self):
        """상태 파일 저장"""
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"상태 저장 실패: {e}")

    def send_telegram_alert(self, market_flag, name, code, rsi_val, close_p):
        """실시간 과대낙폭 감지 알림 전송"""
        if market_flag == "KR":
            url_link = f"https://m.stock.naver.com/domestic/stock/{code}/total"
            title = "🇰🇷 [한국장 4H RSI 과대낙폭 감지]"
            price_str = f"{int(close_p):,}원"
            self.state["kr_signal_found"] = True
        else:
            url_link = f"https://finance.yahoo.com/quote/{code}"
            title = "🇺🇸 [미국장 4H RSI 과대낙폭 감지]"
            price_str = f"${close_p:,.2f}"
            self.state["us_signal_found"] = True
            
        self.save_state()

        message = (
            f"🚨 <b>{title}</b>\n\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{code}</code>)\n"
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

    def send_daily_summary(self, market_flag, date_str):
        """하루 동안 타점이 없을 경우 마감 시간에 발송하는 하트비트 보고"""
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        
        if market_flag == "KR":
            title = "🇰🇷 [한국장 일일 마감 보고]"
            content = f"• 날짜: {date_str}\n• 스캔 결과: 오늘 장 마감(프리~애프터장 포함)까지 <b>4시간봉 RSI 30 이하</b>인 과대낙폭 종목이 <b>발견되지 않았습니다.</b>"
            self.state["kr_summary_sent"] = True
        else:
            title = "🇺🇸 [미국장 일일 마감 보고]"
            content = f"• 날짜: {date_str}\n• 스캔 결과: 오늘 장 마감(프리~애프터장 포함)까지 <b>4시간봉 RSI 30 이하</b>인 과대낙폭 종목이 <b>발견되지 않았습니다.</b>"
            self.state["us_summary_sent"] = True
            
        self.save_state()

        message = (
            f"📊 <b>{title}</b>\n\n"
            f"{content}\n\n"
            f"<i>(🟢 시스템 정상 작동 중 · 내일 장에서 뵙겠습니다)</i>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(self.api_url, data=payload)
        print(f"  └─> [{market_flag} 일일 마감 보고 전송 완료]")

    # ==================== [1. 한국 주식 파이프라인] ====================
    def get_kr_top100(self):
        urls = [
            "https://finance.naver.com/sise/sise_quant.naver",
            "https://finance.naver.com/sise/sise_quant_high.naver"
        ]
        headers = {"User-Agent": "Mozilla/5.0"}
        stocks = {}
        for u in urls:
            res = requests.get(u, headers=headers)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if "/item/main.naver?code=" in a["href"]:
                    m = re.search(r"code=(\d{6})", a["href"])
                    if m and a.text.strip():
                        stocks[m.group(1)] = a.text.strip()
        return stocks

    def fetch_kr_4h_rsi(self, code, period=14):
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=60&count=300&requestType=1"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if res.status_code != 200:
            return None, None
            
        root = ET.fromstring(res.text)
        data = []
        for item in root.findall(".//item"):
            raw = item.attrib["data"].split("|")
            dt = pd.to_datetime(raw[0], format="%Y%m%d%H%M%S")
            data.append([dt, int(raw[1]), int(raw[2]), int(raw[3]), int(raw[4]), int(raw[5])])
            
        if len(data) < 30:
            return None, None
            
        df = pd.DataFrame(data, columns=["datetime", "open", "high", "low", "close", "volume"]).set_index("datetime")
        df_4h = df.resample("4h", label="left", closed="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        
        delta = df_4h["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        df_4h["RSI"] = 100 - (100 / (1 + rs))
        return float(df_4h["RSI"].iloc[-1]), float(df_4h["close"].iloc[-1])

    # ==================== [2. 미국 주식 파이프라인] ====================
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

    # ==================== [3. 메인 실행 루틴] ====================
    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = kst_now.strftime('%Y-%m-%d')
        
        print(f" [시스템 실행] KST 시간: {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (UTC {utc_hour}시)")

        # 1) 🇰🇷 한국장 모니터링 (KST 08:00 ~ 20:00 / UTC 23시 ~ 11시)
        if utc_hour == 23 or 0 <= utc_hour <= 11:
            print("\n [🇰🇷 한국 주식시장 스캔 중...]")
            kr_stocks = self.get_kr_top100()
            for code, name in kr_stocks.items():
                try:
                    rsi, close_p = self.fetch_kr_4h_rsi(code)
                    if rsi and rsi <= 30.0:
                        self.send_telegram_alert("KR", name, code, rsi, close_p)
                    time.sleep(0.1)
                except Exception:
                    continue
            
            # 한국장 마감 시간 체크 (UTC 11시 == KST 오후 8시, 한국장 애프터장 종료 직후)
            if utc_hour == 11 and not self.state["kr_summary_sent"]:
                if not self.state["kr_signal_found"]:
                    self.send_daily_summary("KR", date_str)
                else:
                    self.state["kr_summary_sent"] = True
                    self.save_state()

        # 2) 🇺🇸 미국장 모니터링 (KST 17:00 ~ 익일 09:00 / UTC 08시 ~ 23시 및 00시)
        if 8 <= utc_hour <= 23 or utc_hour == 0:
            print("\n [🇺🇸 미국 주식시장 스캔 중...]")
            us_stocks = self.get_us_top100()
            for ticker, name in us_stocks.items():
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi and rsi <= 30.0:
                        self.send_telegram_alert("US", name, ticker, rsi, close_p)
                    time.sleep(0.3)
                except Exception:
                    continue
            
            # 미국장 마감 시간 체크 (UTC 01시 == KST 오전 10시, 미국 애프터장 완전 종료 후)
            # 깃허브 액션이 UTC 01시에 돌거나, 미국장 마지막 타임인 UTC 0시~1시에 마감 보고 처리
            if utc_hour == 1 and not self.state["us_summary_sent"]:
                if not self.state["us_signal_found"]:
                    self.send_daily_summary("US", date_str)
                else:
                    self.state["us_summary_sent"] = True
                    self.save_state()

if __name__ == "__main__":
    bot = DualMarketRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()