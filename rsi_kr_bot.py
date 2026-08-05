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

    def load_state(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        today_str = kst_now.strftime('%Y-%m-%d')
        
        default_state = {
            "date": today_str,
            "signal_found": False,
            "summary_sent": False
        }
        
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

    def send_telegram_alert(self, name, code, rsi_val, close_p):
        url_link = f"https://m.stock.naver.com/domestic/stock/{code}/total"
        price_str = f"{int(close_p):,}원"
        self.state["signal_found"] = True
        self.save_state()

        message = (
            f"🚨 <b>🇰🇷 [한국장 4H RSI 과대낙폭 감지]</b>\n\n"
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

    def send_test_summary_alert(self, results):
        """[테스트 전용] 요청된 수량만큼의 4H RSI 요약 메시지 발송 (30개 단위 분할 전송)"""
        text_lines = []
        for i, (name, code, rsi, price) in enumerate(results, 1):
            text_lines.append(f"{i}. <b>{name}</b> (<code>{code}</code>) | RSI: <b>{rsi:.2f}</b> | {int(price):,}원")
        
        chunk_size = 30
        for i in range(0, len(text_lines), chunk_size):
            chunk = text_lines[i:i + chunk_size]
            page_info = f" ({i//chunk_size + 1}/{(len(text_lines)-1)//chunk_size + 1})" if len(text_lines) > chunk_size else ""
            
            message = (
                f"🧪 <b>🇰🇷 [한국장 상위 {len(results)}개 종목 4H RSI 테스트 리포트]{page_info}</b>\n\n"
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
        print(f"  └─> [한국장 상위 {len(results)}개 테스트 리포트 전송 완료]")

    def send_daily_summary(self, date_str):
        self.state["summary_sent"] = True
        self.save_state()

        message = (
            f"📊 <b>🇰🇷 [한국장 일일 마감 보고]</b>\n\n"
            f"• 기준 날짜: {date_str}\n"
            f"• 스캔 결과: 오늘 장 마감(프리~애프터장 포함)까지 <b>4시간봉 RSI 30 이하</b>인 과대낙폭 종목이 <b>발견되지 않았습니다.</b>\n\n"
            f"<i>(🟢 한국장 스캐너 정상 작동 중 · 내일 장에서 뵙겠습니다)</i>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        requests.post(self.api_url, data=payload)
        print("  └─> [한국장 일일 마감 보고 전송 완료]")

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

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        
        print(f" [🇰🇷 한국장 스캐너 실행] KST 시간: {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (UTC {utc_hour}시)")

        # 🧪 [1. 텔레그램 '/testN' 명령어 감지 (10~100개)]
        cmd_found, test_count = self.check_telegram_test_command()
        if cmd_found:
            print(f"\n [🧪 한국장 텔레그램 '/test' 감지: 상위 {test_count}개 종목 RSI 요약 발송 중...]")
            kr_stocks = self.get_kr_top100()
            target_items = list(kr_stocks.items())[:test_count]
            
            test_results = []
            for code, name in target_items:
                try:
                    rsi, close_p = self.fetch_kr_4h_rsi(code)
                    if rsi:
                        test_results.append((name, code, rsi, close_p))
                    time.sleep(0.05)
                except Exception:
                    continue
            if test_results:
                self.send_test_summary_alert(test_results)

        # 🟢 [2. 일반 실전 감시 모드] 30 이하 과대낙폭 종목 스캔 및 마감 보고 체크
        if utc_hour == 23 or 0 <= utc_hour <= 11:
            kr_stocks = self.get_kr_top100()
            for code, name in kr_stocks.items():
                try:
                    rsi, close_p = self.fetch_kr_4h_rsi(code)
                    if rsi and rsi <= 30.0:
                        self.send_telegram_alert(name, code, rsi, close_p)
                    time.sleep(0.05)
                except Exception:
                    continue
            
            if utc_hour in [11, 12] and not self.state["summary_sent"]:
                if not self.state["signal_found"]:
                    self.send_daily_summary(date_str)
                else:
                    self.state["summary_sent"] = True
                    self.save_state()

if __name__ == "__main__":
    bot = KoreaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()