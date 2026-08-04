import os
import re
import time
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

class DualMarketRSIBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_telegram_alert(self, market_flag, name, code, rsi_val, close_p, currency="원"):
        """한국/미국 구분 이모지 및 해당 증권사 링크가 포함된 텔레그램 알림 전송"""
        if market_flag == "KR":
            url_link = f"https://m.stock.naver.com/domestic/stock/{code}/total"
            title = "🇰🇷 [한국장 4H RSI 과대낙폭 감지]"
            price_str = f"{int(close_p):,}원"
        else:
            url_link = f"https://finance.yahoo.com/quote/{code}"
            title = "🇺🇸 [미국장 4H RSI 과대낙폭 감지]"
            price_str = f"${close_p:,.2f}"
            
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
        res = requests.post(self.api_url, data=payload)
        if res.status_code == 200:
            print(f"  └─> [텔레그램 알림 전송 완료]: {name} ({code})")

    # ==================== [1. 한국 주식 (KRX) 파이프라인] ====================
    def get_kr_top100(self):
        """네이버 금융 거래량/거래대금 TOP 100 합집합 추출"""
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
        """네이버 0초 지연 실시간 60분봉 -> 4시간봉 RSI 계산"""
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=60&count=300&requestType=0"
        res = requests.get(url)
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

    # ==================== [2. 미국 주식 (US) 파이프라인] ====================
    def get_us_top100(self):
        """
        미국 나스닥/NYSE 시장을 이끄는 빅테크 및 주도주 100개 대표 유니버스
        (S&P500 + 나스닥100 + 반도체/AI/성장주 핵심 거래량 상위 종목)
        """
        us_tickers = {
            "AAPL": "애플", "NVDA": "엔비디아", "TSLA": "테슬라", "MSFT": "마이크로소프트",
            "AMZN": "아마존", "GOOGL": "알파벳(구글)", "META": "메타", "AMD": "AMD",
            "NFLX": "넷플릭스", "AVGO": "브로드컴", "INTC": "인텔", "QCOM": "퀄컴",
            "ARM": "ARM 홀딩스", "PLTR": "팔란티어", "SMCI": "슈퍼마이크로", "MU": "마이크론",
            "TSM": "TSMC", "ASML": "ASML", "COIN": "코인베이스", "SOFI": "소파이",
            "MSTR": "마이크로스트래티지", "LLY": "일라이릴리", "UBER": "우버", "DIS": "디즈니",
            "CRWD": "크라우드스트라이크", "SNOW": "스노우플레이크", "PANW": "팔로알토",
            "V": "비자", "MA": "마스터카드", "JPM": "JP모건", "JNJ": "존슨앤드존슨",
            "WMT": "월마트", "COST": "코스트코", "AMD": "AMD", "TXN": "텍사스인스트루먼트"
            # 필요 시 원하는 티커를 100개 이상 얼마든지 추가 가능합니다.
        }
        return us_tickers

    def fetch_us_4h_rsi(self, ticker, period=14):
        """yfinance 실시간 1시간봉 -> 4시간봉 RSI 계산"""
        df = yf.download(ticker, period="1mo", interval="1h", progress=False)
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

    # ==================== [3. 시간대별 자동 시장 구동 루틴] ====================
    def run(self):
        # 현재 UTC 시각 및 한국시간(KST, UTC+9) 계산
        now_utc = datetime.datetime.utcnow()
        utc_hour = now_utc.hour
        
        print(f" [시스템 실행 시작] UTC 기준 시간: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")

        # 1) 한국 주식시장 시간인지 체크 (UTC 0시~6시 -> 한국 09:00~15:30)
        if 0 <= utc_hour <= 6:
            print("\n [🇰🇷 한국장 실시간 모니터링 모드 활성화]")
            kr_stocks = self.get_kr_top100()
            print(f">> 한국 주도주 {len(kr_stocks)}개 종목 분석 중...")
            for code, name in kr_stocks.items():
                try:
                    rsi, close_p = self.fetch_kr_4h_rsi(code)
                    if rsi and rsi <= 30.0:
                        self.send_telegram_alert("KR", name, code, rsi, close_p)
                    time.sleep(0.1)
                except Exception:
                    continue

        # 2) 미국 주식시장 시간인지 체크 (UTC 13시~21시 -> 미국 서머타임 포함 정규장 전체 커버)
        elif 13 <= utc_hour <= 21:
            print("\n [🇺🇸 미국장 실시간 모니터링 모드 활성화]")
            us_stocks = self.get_us_top100()
            print(f">> 미국 주도주 {len(us_stocks)}개 종목 분석 중...")
            for ticker, name in us_stocks.items():
                try:
                    rsi, close_p = self.fetch_us_4h_rsi(ticker)
                    if rsi and rsi <= 30.0:
                        self.send_telegram_alert("US", name, ticker, rsi, close_p)
                    time.sleep(0.3)
                except Exception:
                    continue
        else:
            print(">> 현재 한국장 및 미국장 정규 거래 시간이 아닙니다. 스캔을 건너empty니다.")

if __name__ == "__main__":
    bot = DualMarketRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()