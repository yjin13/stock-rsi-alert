import os
import re
import time
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

# 1) GitHub Secrets 환경변수에서 텔레그램 정보 불러오기 (없으면 직접 입력 가능)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")

class ZeroCostTelegramRSIBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_telegram_alert(self, name, code, rsi_val, close_p):
        """텔레그램 HTML 포맷 알림 전송"""
        naver_url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
        
        # HTML 형식 메시지 구성
        message = (
            f"🚨 <b>[4시간봉 RSI 과대낙폭 감지]</b>\n\n"
            f"• <b>종목명:</b> <a href='{naver_url}'>{name}</a> ({code})\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> {close_p:,}원\n\n"
            f"👉 <a href='{naver_url}'>네이버 증권 차트 확인하기</a>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        res = requests.post(self.api_url, data=payload)
        if res.status_code == 200:
            print(f"  └─> [텔레그램 전송 성공]: {name}")
        else:
            print(f"  └─> [텔레그램 전송 실패]: {res.text}")

    def get_top100_stocks(self):
        """네이버 금융에서 '거래량 TOP 100' + '거래대금 TOP 100' 합집합(중복제거) 추출"""
        urls = [
            "https://finance.naver.com/sise/sise_quant.naver",      # 거래량 상위
            "https://finance.naver.com/sise/sise_quant_high.naver"  # 거래대금 상위
        ]
        headers = {"User-Agent": "Mozilla/5.0"}
        stock_dict = {}

        print(">> [실시간 시장 주도주] 거래량 & 거래대금 TOP 100 종목 수집 중...")
        for url in urls:
            res = requests.get(url, headers=headers)
            soup = BeautifulSoup(res.text, "html.parser")
            
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/item/main.naver?code=" in href:
                    match = re.search(r"code=(\d{6})", href)
                    if match:
                        code = match.group(1)
                        name = a_tag.text.strip()
                        if name and code not in stock_dict:
                            stock_dict[code] = name

        print(f">> 총 {len(stock_dict)}개 주도주 유니버스 추출 완료!\n")
        return stock_dict

    def fetch_realtime_4h_rsi(self, code, period=14):
        """네이버 차트 실시간 60분봉 300개 수집 -> 4시간봉(240분봉) 변환 -> Wilder's RSI(14) 계산"""
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=60&count=300&requestType=0"
        res = requests.get(url)
        if res.status_code != 200:
            return None, None

        root = ET.fromstring(res.text)
        data_list = []
        for item in root.findall(".//item"):
            raw = item.attrib["data"].split("|")
            dt = pd.to_datetime(raw[0], format="%Y%m%d%H%M%S")
            data_list.append([dt, int(raw[1]), int(raw[2]), int(raw[3]), int(raw[4]), int(raw[5])])

        if len(data_list) < 30:
            return None, None

        df = pd.DataFrame(data_list, columns=["datetime", "open", "high", "low", "close", "volume"])
        df = df.set_index("datetime")
        
        # 4시간봉 변환
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
        
        return float(df_4h["RSI"].iloc[-1]), int(df_4h["close"].iloc[-1])

    def run(self):
        watch_list = self.get_top100_stocks()
        print("== 4시간봉 RSI(30 이하) 전체 스캔 시작 ==")
        for code, name in watch_list.items():
            try:
                rsi, close_p = self.fetch_realtime_4h_rsi(code)
                if rsi is None:
                    continue
                
                print(f"{name} ({code}) | 4시간봉 RSI: {rsi:.2f} | 현재가: {close_p:,}원")
                
                # RSI 30 이하 감지 시 텔레그램 전송
                if rsi <= 30.0:
                    self.send_telegram_alert(name, code, rsi, close_p)
                
                time.sleep(0.1) # 서버 보호를 위한 0.1초 대기
            except Exception as e:
                continue

if __name__ == "__main__":
    bot = ZeroCostTelegramRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()