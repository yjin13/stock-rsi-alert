import os
import re
import time
import json
import datetime
import requests
from bs4 import BeautifulSoup

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
        except Exception as e:
            print(f"한국장 상태 저장 실패: {e}")

    def is_valid_kr_stock(self, name):
        for kw in ["인버스", "곱버스", "PUT", "put", "선물인버스"]:
            if kw in name:
                return False
        return True

    def get_kr_top100(self):
        """네이버에서 상위 100개 종목 코드를 가져옴"""
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

    def fetch_tv_bulk_rsi(self, codes):
        """💡 트레이딩뷰 본사 API 다이렉트 호출 (한국장)"""
        url = "https://scanner.tradingview.com/korea/scan"
        payload = {
            "filter": [{"left": "name", "operation": "in_range", "right": codes}],
            "columns": ["name", "close", "RSI|240"]
        }
        try:
            res = requests.post(url, json=payload, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = res.json()
            results = {}
            for item in data.get("data", []):
                ticker = item["d"][0]
                close_p = item["d"][1]
                rsi_val = item["d"][2]
                if rsi_val is not None:
                    results[ticker] = (rsi_val, close_p)
            return results
        except Exception as e:
            print(f"TV API 에러: {e}")
            return {}

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
        requests.post(self.api_url, data={
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })

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
            f"<i>(🟢 한국장 스캐너 정상 작동 중 · 내일 장에서 뵙겠습니다)</i>"
        )
        requests.post(self.api_url, data={
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        check_time_str = kst_now.strftime('%Y-%m-%d %H:%M KST')
        
        if kst_now.weekday() >= 5:
            print(f" [휴장일] 주말이므로 실행하지 않습니다. ({check_time_str})")
            return

        print(f" [🇰🇷 한국장 트레이딩뷰 연동 스캐너 실행] KST 시간: {check_time_str} (UTC {utc_hour}시)")

        if utc_hour in [0, 1, 2, 3, 4, 5, 6, 7]:
            kr_stocks = self.get_kr_top100()
            codes = list(kr_stocks.keys())
            
            # 🔥 트레이딩뷰에서 한국장 데이터도 한 번에 싹 긁어옴!
            tv_data = self.fetch_tv_bulk_rsi(codes)
            
            for code, name in kr_stocks.items():
                if code in tv_data:
                    rsi, close_p = tv_data[code]
                    
                    if rsi <= RSI_THRESHOLD:
                        self.send_telegram_alert(name, code, rsi, close_p, check_time_str)
            
        if utc_hour in [7, 8, 9] and not self.state["summary_sent"]:
            self.send_daily_summary(date_str, self.state.get("signal_count", 0))

if __name__ == "__main__":
    bot = KoreaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()