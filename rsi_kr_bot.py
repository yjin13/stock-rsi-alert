import os
import re
import time
import json
import datetime
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pandas as pd
import holidays

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
STATE_FILE = "kr_state.json"
RSI_THRESHOLD = 40.0  # <--- 🎯 원하는 RSI 수치

class KoreaRSIBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.state = self.load_state()

    def load_state(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        today_str = kst_now.strftime('%Y-%m-%d')
        default_state = {"date": today_str, "signal_count": 0, "summary_sent": False}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") != today_str:
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

    def is_valid_kr_stock(self, name):
        for kw in ["인버스", "곱버스", "PUT", "put", "선물인버스"]:
            if kw in name:
                return False
        return True

    def get_kr_top100(self):
        urls = [
            "https://finance.naver.com/sise/sise_quant.naver",             
            "https://finance.naver.com/sise/sise_quant.naver?sosok=1",     
            "https://finance.naver.com/sise/sise_quant_high.naver",        
            "https://finance.naver.com/sise/sise_quant_high.naver?sosok=1" 
        ]
        headers = {"User-Agent": "Mozilla/5.0"}
        stocks = {}
        for u in urls:
            res = requests.get(u, headers=headers)
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if "/item/main.naver?code=" in a["href"]:
                    m = re.search(r"code=([0-9A-Za-z]{6})", a["href"])
                    if m and a.text.strip():
                        stock_name = a.text.strip()
                        if self.is_valid_kr_stock(stock_name):
                            stocks[m.group(1)] = stock_name
        return stocks

    def send_telegram_alert(self, name, code, rsi_val, close_p, check_time):
        url_link = f"https://m.stock.naver.com/domestic/stock/{code}/total"
        self.state["signal_count"] = self.state.get("signal_count", 0) + 1
        self.save_state()
        message = (
            f"🚨 <b>🇰🇷 [한국장 4H RSI {int(RSI_THRESHOLD)} 이하 감지]</b>\n\n"
            f"• <b>기준 시간:</b> {check_time}\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{code}</code>)\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> {int(close_p):,}원\n\n"
            f"👉 <a href='{url_link}'>실시간 차트 확인하기</a>"
        )
        requests.post(self.api_url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})

    def send_daily_summary(self, date_str, signal_count):
        self.state["summary_sent"] = True
        self.save_state()
        if signal_count == 0:
            result_text = f"오늘 장 마감까지 <b>4시간봉 RSI {int(RSI_THRESHOLD)} 이하</b> 종목이 <b>발견되지 않았습니다.</b>"
        else:
            result_text = f"오늘 장 마감까지 <b>4시간봉 RSI {int(RSI_THRESHOLD)} 이하</b> 신호가 <b>총 {signal_count}건</b> 감지되었습니다."

        message = (
            f"📈 <b>🇰🇷 [한국장 일일 마감 보고]</b>\n\n"
            f"• <b>기준 날짜:</b> {date_str}\n"
            f"• <b>스캔 결과:</b> {result_text}\n\n"
            f"<i>(🟢 코스피/코스닥 스캐너 정상 작동 중)</i>"
        )
        requests.post(self.api_url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})

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

    def fetch_kr_4h_rsi(self, code, period=14):
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=60&count=2000&requestType=1"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if res.status_code != 200:
            return None, None
            
        root = ET.fromstring(res.text)
        data = []
        for item in root.findall(".//item"):
            raw = item.attrib["data"].split("|")
            dt = pd.to_datetime(raw[0], format="%Y%m%d%H%M%S")
            data.append([dt, int(raw[1]), int(raw[2]), int(raw[3]), int(raw[4]), int(raw[5])])
            
        if len(data) < 50:
            return None, None
            
        df = pd.DataFrame(data, columns=["datetime", "open", "high", "low", "close", "volume"]).set_index("datetime")
        df_4h = df.resample("4h", origin="2024-01-01 09:00:00", label="left", closed="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()
        
        rsi_val = self.calc_tradingview_rsi(df_4h["close"], period)
        if rsi_val is None:
            return None, None
        return rsi_val, float(df_4h["close"].iloc[-1])

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        check_time_str = kst_now.strftime('%Y-%m-%d %H:%M KST')
        
        kr_holidays = holidays.KR()
        
        if kst_now.weekday() >= 5 or kst_now.date() in kr_holidays:
            print(f" [휴장일] 주말 또는 공휴일이므로 한국장 스캐너를 실행하지 않습니다. ({check_time_str})")
            return

        print(f" [🇰🇷 한국장 스캐너 실행] KST 시간: {check_time_str}")

        if utc_hour in [0, 1, 2, 3, 4, 5, 6, 7]:
            kr_stocks = self.get_kr_top100()
            for code, name in kr_stocks.items():
                try:
                    rsi, close_p = self.fetch_kr_4h_rsi(code)
                    if rsi and rsi <= RSI_THRESHOLD:
                        self.send_telegram_alert(name, code, rsi, close_p, check_time_str)
                    time.sleep(0.05)
                except Exception:
                    continue
            
        if utc_hour in [7, 8, 9] and not self.state["summary_sent"]:
            self.send_daily_summary(date_str, self.state.get("signal_count", 0))

if __name__ == "__main__":
    bot = KoreaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()