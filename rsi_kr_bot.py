import os
import re
import time
import json
import datetime
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pandas as pd

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
STATE_FILE = "kr_state.json"

class KoreaRSIBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.state = self.load_state()

    def load_state(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        today_str = kst_now.strftime('%Y-%m-%d')
        default_state = {"date": today_str, "signal_found": False, "summary_sent": False}
        
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
        except Exception as e:
            print(f"한국장 상태 저장 실패: {e}")

    def is_valid_kr_stock(self, name):
        """💡 인버스(역추세) ETF 및 불필요한 파생 종목 자동 제외 필터"""
        for kw in ["인버스", "곱버스", "PUT", "put", "선물인버스"]:
            if kw in name:
                return False
        return True

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
                        stock_name = a.text.strip()
                        if self.is_valid_kr_stock(stock_name):
                            stocks[m.group(1)] = stock_name
        return stocks

    def send_telegram_alert(self, name, code, rsi_val, close_p, check_time):
        url_link = f"https://m.stock.naver.com/domestic/stock/{code}/total"
        self.state["signal_found"] = True
        self.save_state()

        message = (
            f"🚨 <b>🇰🇷 [한국장 4H RSI 과대낙폭 감지]</b>\n\n"
            f"• <b>기준 시간:</b> {check_time}\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{code}</code>)\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> {int(close_p):,}원\n\n"
            f"👉 <a href='{url_link}'>실시간 차트 확인하기</a>"
        )
        requests.post(self.api_url, data={
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })

    def send_top30_summary(self, results, check_time):
        """🧪 [테스트/점검용 기능] 필요 시 주석을 풀면 상위 30개 종목 4H RSI 리포트 발송"""
        text_lines = [
            f"{i}. <b>{name}</b> (<code>{code}</code>) | RSI: <b>{rsi:.2f}</b> | {int(price):,}원"
            for i, (name, code, rsi, price) in enumerate(results[:30], 1)
        ]
        message = (
            f"📊 <b>🇰🇷 [한국장 상위 30개 종목 4H RSI 정기 리포트]</b>\n"
            f"• <b>기준 시간:</b> {check_time}\n\n"
            + "\n".join(text_lines)
            + "\n\n<i>(🟢 트레이딩뷰 RSI 공식 적용 완료)</i>"
        )
        requests.post(self.api_url, data={
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })
        print("  └─> [한국장 상위 30개 정기 리포트 전송 완료]")

    def send_daily_summary(self, date_str):
        self.state["summary_sent"] = True
        self.save_state()

        message = (
            f"📈 <b>🇰🇷 [한국장 일일 마감 보고]</b>\n\n"
            f"• <b>기준 날짜:</b> {date_str}\n"
            f"• <b>스캔 결과:</b> 오늘 장 마감까지 <b>4시간봉 RSI 30 이하</b> 과대낙폭 종목이 <b>발견되지 않았습니다.</b>\n\n"
            f"<i>(🟢 한국장 스캐너 정상 작동 중 · 내일 장에서 뵙겠습니다)</i>"
        )
        requests.post(self.api_url, data={
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })
        print("  └─> [한국장 일일 마감 보고 전송 완료]")

    def calc_tradingview_rsi(self, close_series, period=14):
        """💡 트레이딩뷰 Pine Script(Wilder's RMA) 공식과 100% 동일한 RSI 계산 알고리즘"""
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
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=60&count=500&requestType=1"
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
        
        # 한국장 오전 09:00 기준으로 4시간봉 정렬 (09:00~13:00 / 13:00~15:30)
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
        
        print(f" [🇰🇷 한국장 스캐너 실행] KST 시간: {check_time_str} (UTC {utc_hour}시)")

        # 💡 UTC 0~7시 -> KST 09:15(오전 9시 15분) ~ 16:15(오후 4시 15분) 한국 정규장+마감 시간에만 작동!
        if utc_hour in [0, 1, 2, 3, 4, 5, 6, 7]:
            kr_stocks = self.get_kr_top100()
            top30_results = []
            
            for code, name in kr_stocks.items():
                try:
                    rsi, close_p = self.fetch_kr_4h_rsi(code)
                    if rsi:
                        if len(top30_results) < 30:
                            top30_results.append((name, code, rsi, close_p))
                        if rsi <= 30.0:
                            self.send_telegram_alert(name, code, rsi, close_p, check_time_str)
                    time.sleep(0.05)
                except Exception:
                    continue
            
            # 🧪 정기 리포트 발송 중지 (필요 시 아래 줄 주석(#)을 제거하면 발송됨)
            # if top30_results:
            #     self.send_top30_summary(top30_results, check_time_str)
            
            # 장 마감 직후인 오후 4시 15분(UTC 7시)에 일일 마감 보고
            if utc_hour == 7 and not self.state["summary_sent"]:
                if not self.state["signal_found"]:
                    self.send_daily_summary(date_str)
                else:
                    self.state["summary_sent"] = True
                    self.save_state()

if __name__ == "__main__":
    bot = KoreaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()