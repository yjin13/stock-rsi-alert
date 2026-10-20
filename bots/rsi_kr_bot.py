import os
import re
import json
import datetime
import requests
import pandas as pd
import holidays
from lib.kis_client import KISClient
from lib.rsi_common import DATA_DIR, BarCache, wilder_rsi, resample_4h_close, split_complete

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
KIS_APP_KEY = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
STATE_FILE = os.path.join(DATA_DIR, "kr_state.json")
CACHE_FILE = os.path.join(DATA_DIR, "kr_4h_cache.json")  # 종목별 '완성된' 4시간봉 종가 캐시(증분 갱신용)
RSI_THRESHOLD = 30.0  # 🎯 원하는 RSI 수치
KR_SESSION_CLOSE = datetime.time(15, 30)
BAR_ORIGIN = "2024-01-01 09:00:00"  # 4시간봉 경계: 09:00~13:00, 13:00~15:30
MIN_4H_BARS = 100  # RSI 수렴을 위한 최소 4시간봉 개수
BACKFILL_DAYS = 100  # 신규 종목 백필 구간(달력일, 약 140개 4시간봉)
BACKFILL_LIMIT = int(os.environ.get("KR_BACKFILL_LIMIT", "20"))  # 실행당 신규 종목 백필 한도
INCLUDE_FORMING_BAR = True  # 진행 중인 4시간봉도 RSI에 반영(HTS 화면·실시간 알림 기준)

class KoreaRSIBot:
    def __init__(self, token, chat_id, kis):
        self.token = token
        self.chat_id = chat_id
        self.kis = kis
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.state = self.load_state()
        self.cache = BarCache(CACHE_FILE)
        self.backfill_budget = BACKFILL_LIMIT

    def load_state(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        today_str = kst_now.strftime('%Y-%m-%d')
        default_state = {"date": today_str, "signal_count": 0, "summary_sent": False, "alerted": []}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") != today_str:
                        return default_state
                    if "alerted" not in data:
                        data["alerted"] = []
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
        # 네이버 금융 구 페이지(sise_quant.naver)가 새 사이트로 리다이렉트되어 종목이 0개로 잡히던 문제 →
        # 모바일 JSON API(거래량 상위, 코스피·코스닥 각 100개)로 대체
        headers = {"User-Agent": "Mozilla/5.0"}
        stocks = {}
        for market in ("KOSPI", "KOSDAQ"):
            try:
                res = requests.get(
                    f"https://m.stock.naver.com/api/stocks/quantTop/{market}",
                    params={"page": 1, "pageSize": 100}, headers=headers, timeout=10,
                )
                res.raise_for_status()
                for item in res.json().get("stocks", []):
                    code, name = item.get("itemCode"), (item.get("stockName") or "").strip()
                    if re.fullmatch(r"[0-9A-Za-z]{6}", code or "") and name and self.is_valid_kr_stock(name):
                        stocks[code] = name
            except Exception as e:
                print(f" [종목 목록 실패] {market}: {e}")
        return stocks

    def send_telegram_alert(self, name, code, rsi_val, close_p, check_time):
        url_link = f"https://m.stock.naver.com/domestic/stock/{code}/total"
        self.state["signal_count"] = self.state.get("signal_count", 0) + 1
        self.save_state()
        message = (
            f"🚨 <b>🇰🇷 [한국장 4H RSI {int(RSI_THRESHOLD)} 이하 감지]</b>\n\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{code}</code>)\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> {int(close_p):,}원\n"
            f"• <b>기준 시간:</b> {check_time}"
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
            f"• <b>스캔 결과:</b> {result_text}"
        )
        requests.post(self.api_url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})

    def fetch_kr_4h_rsi(self, code, now, period=14):
        today_str = now.strftime('%Y-%m-%d')
        hist = self.cache.closes(code)

        if hist.empty:
            if self.backfill_budget <= 0:
                return None, None  # 이번 실행의 백필 한도 초과 → 다음 실행에서 처리
            self.backfill_budget -= 1
            start = datetime.datetime.combine((now - datetime.timedelta(days=BACKFILL_DAYS)).date(), datetime.time(9, 0))
        else:
            start = (hist.index[-1] + pd.Timedelta(hours=4)).to_pydatetime()  # 첫 미수집 봉 시작

        last_price = None
        forming = pd.Series(dtype=float)
        if start <= now:
            df_1m = self.kis.get_minute_candles(code, start, now)
            if len(df_1m):
                complete, forming = split_complete(resample_4h_close(df_1m, BAR_ORIGIN), now, KR_SESSION_CLOSE)
                hist = complete if hist.empty else pd.concat([hist, complete])
                hist = hist[~hist.index.duplicated(keep="last")].sort_index()
                last_price = float(df_1m["close"].iloc[-1])

        if len(hist):
            self.cache.update(code, hist, today_str)

        series = pd.concat([hist, forming]) if INCLUDE_FORMING_BAR and len(forming) else hist
        if len(series) < MIN_4H_BARS:
            return None, None

        rsi_val = wilder_rsi(series, period)
        if rsi_val is None:
            return None, None
        return rsi_val, last_price if last_price is not None else float(series.iloc[-1])

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
            self.kis.issue_token()  # 실패하면 예외로 워크플로를 실패시켜 알 수 있게 한다
            kr_stocks = self.get_kr_top100()
            if not kr_stocks:
                raise RuntimeError("한국장 종목 목록이 비어 있습니다(네이버 응답 형식 변경 의심)")  # 조용히 넘어가지 않고 워크플로를 실패시킨다
            now = kst_now.replace(tzinfo=None)
            failed = skipped = 0
            try:
                for code, name in kr_stocks.items():
                    try:
                        rsi, close_p = self.fetch_kr_4h_rsi(code, now)
                        if rsi is None:
                            skipped += 1
                        elif rsi <= RSI_THRESHOLD and code not in self.state.get("alerted", []):
                            self.send_telegram_alert(name, code, rsi, close_p, check_time_str)
                            self.state["alerted"].append(code)
                            self.save_state()
                    except Exception as e:
                        failed += 1
                        print(f" [조회 실패] {name}({code}): {e}")
            finally:
                self.cache.prune(pd.Timestamp(now))
                self.cache.save()  # 중간에 끊겨도 백필 진행분을 보존
            print(f" [스캔 완료] 대상 {len(kr_stocks)}종목, 데이터 부족/백필 대기 {skipped}종목, 실패 {failed}종목")

        if utc_hour in [7, 8, 9] and not self.state["summary_sent"]:
            self.send_daily_summary(date_str, self.state.get("signal_count", 0))

if __name__ == "__main__":
    kis = KISClient(KIS_APP_KEY, KIS_APP_SECRET)
    bot = KoreaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, kis)
    bot.run()
