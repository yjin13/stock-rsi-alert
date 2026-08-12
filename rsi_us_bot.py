import os
import time
import json
import datetime
import requests

# 💡 텔레그램 설정 및 RSI 알림 기준 변수
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
STATE_FILE = "us_state.json"
RSI_THRESHOLD = 40.0  # <--- 🎯 원하는 RSI 수치

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
        default_state = {"date": session_date, "signal_count": 0, "summary_sent": False}
        
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
        # 트레이딩뷰 티커 기호(BRK.B)를 야후 링크용으로 변환 처리
        url_ticker = ticker.replace(".", "-")
        url_link = f"https://finance.yahoo.com/quote/{url_ticker}"
        
        self.state["signal_count"] = self.state.get("signal_count", 0) + 1
        self.save_state()

        message = (
            f"🚨 <b>🇺🇸 [미국장 4H RSI {int(RSI_THRESHOLD)} 이하 감지]</b>\n\n"
            f"• <b>기준 시간:</b> {check_time}\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{ticker}</code>)\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> ${close_p:,.2f}\n\n"
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
            result_text = f"밤사이 미국장 마감까지 <b>4시간봉 RSI {int(RSI_THRESHOLD)} 이하</b> 종목이 <b>발견되지 않았습니다.</b>"
        else:
            result_text = f"밤사이 미국장 마감까지 <b>4시간봉 RSI {int(RSI_THRESHOLD)} 이하</b> 신호가 <b>총 {signal_count}건</b> 감지되었습니다."

        message = (
            f"📈 <b>🇺🇸 [미국장 일일 마감 보고]</b>\n\n"
            f"• <b>기준 날짜:</b> {date_str} (오버나이트 세션)\n"
            f"• <b>스캔 결과:</b> {result_text}\n\n"
            f"<i>(🟢 미국장 스캐너 정상 작동 중 · 다음 장에서 뵙겠습니다)</i>"
        )
        requests.post(self.api_url, data={
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })

    def get_us_top100(self):
        return {
            "SPY": "S&P 500 ETF", "QQQ": "나스닥 100 ETF", "DIA": "다우존스 ETF",
            "QLD": "나스닥 100 2배 (QLD)", "SSO": "S&P 500 2배 (SSO)",
            "TQQQ": "나스닥 100 3배 (TQQQ)", "UPRO": "S&P 500 3배 (UPRO)",
            "SOXX": "필라델피아 반도체 ETF", "SOXL": "반도체 3배 (SOXL)",
            "SMH": "반도체 섹터 (SMH)", "USD": "반도체 2배 (USD)",
            "XLK": "기술주 섹터 (XLK)", "TLT": "미국 20년물 국채 ETF",
            "TMF": "미국 20년물 국채 3배 (TMF)",
            "AAPL": "애플", "NVDA": "엔비디아", "MSFT": "마이크로소프트",
            "GOOGL": "알파벳(구글)", "AMZN": "아마존", "META": "메타", "TSLA": "테슬라",
            "AVGO": "브로드컴", "TSM": "TSMC", "AMD": "AMD", "ASML": "ASML",
            "QCOM": "퀄컴", "TXN": "텍사스 인스트루먼트", "MU": "마이크론",
            "INTC": "인텔", "ARM": "ARM 홀딩스", "SMCI": "슈퍼마이크로",
            "PLTR": "팔란티어", "CRWD": "크라우드스트라이크", "SNOW": "스노우플레이크",
            "PANW": "팔로알토", "NKE": "나이키", "WMT": "월마트", "COST": "코스트코",
            "HD": "홈디포", "MCD": "맥도날드", "SBUX": "스타벅스", "DIS": "디즈니",
            "NFLX": "넷플릭스", "UBER": "우버", "PG": "프록터앤드갬블(P&G)",
            "KO": "코카콜라", "PEP": "펩시코", "BRK.B": "버크셔 해서웨이", # TV 맞춤
            "JPM": "JP모건 체이스", "BAC": "뱅크오브아메리카", "V": "비자",
            "MA": "마스터카드", "SOFI": "소파이", "COIN": "코인베이스",
            "MSTR": "마이크로스트래티지", "LLY": "일라이릴리", "UNH": "유나이티드헬스",
            "JNJ": "존슨앤드존슨", "MRK": "머크", "ABBV": "애브비",
            "XOM": "엑슨모빌", "CVX": "쉐브론", "GE": "제너럴 일렉트릭", "CAT": "캐터필러"
        }

    def fetch_tv_bulk_rsi(self, tickers):
        """💡 트레이딩뷰 본사 API 다이렉트 호출: 100개 종목 4H RSI를 1초 만에 그대로 가져옴"""
        url = "https://scanner.tradingview.com/america/scan"
        payload = {
            "filter": [{"left": "name", "operation": "in_range", "right": tickers}],
            "columns": ["name", "close", "RSI|240"]  # RSI|240 = 4시간봉 RSI
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

    def run(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        utc_hour = datetime.datetime.utcnow().hour
        date_str = self.state["date"]
        check_time_str = kst_now.strftime('%Y-%m-%d %H:%M KST')
        
        session_time = kst_now - datetime.timedelta(hours=12)
        if session_time.weekday() >= 5:
            print(f" [휴장일] 미국 현지 주말이므로 실행하지 않습니다. ({check_time_str})")
            return

        print(f" [🇺🇸 미국장 트레이딩뷰 연동 스캐너 실행] KST 시간: {check_time_str} (UTC {utc_hour}시)")

        if utc_hour in [13, 14, 15, 16, 17, 18, 19, 20]:
            us_stocks = self.get_us_top100()
            tickers = list(us_stocks.keys())
            
            # 🔥 야후 안 쓰고 트레이딩뷰에서 70개 종목 한 번에 싹 긁어옴!
            tv_data = self.fetch_tv_bulk_rsi(tickers)
            
            for ticker, name in us_stocks.items():
                if ticker in tv_data:
                    rsi, close_p = tv_data[ticker]
                    
                    if rsi <= RSI_THRESHOLD:
                        self.send_telegram_alert(name, ticker, rsi, close_p, check_time_str)
            
        current_month = datetime.datetime.utcnow().month
        is_dst = 3 <= current_month <= 11
        summary_hours = [20, 21, 22] if is_dst else [21, 22, 23]
        
        if utc_hour in summary_hours and not self.state["summary_sent"]:
            self.send_daily_summary(date_str, self.state.get("signal_count", 0))

if __name__ == "__main__":
    bot = USAmericaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()