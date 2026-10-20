import os
import json
import datetime
import requests
import pandas as pd
import holidays
from zoneinfo import ZoneInfo
from lib.kis_client import KISClient
from lib.history_seed import fetch_us_4h_seed
from lib.rsi_common import DATA_DIR, BarCache, wilder_rsi, resample_4h_close, split_complete

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
KIS_APP_KEY = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
STATE_FILE = os.path.join(DATA_DIR, "us_state.json")
CACHE_FILE = os.path.join(DATA_DIR, "us_4h_cache.json")  # 종목별 '완성된' 4시간봉 종가 + KIS 거래소 코드 캐시
RSI_THRESHOLD = 30.0  # 🎯 원하는 RSI 수치
US_SESSION_OPEN = datetime.time(9, 30)
US_SESSION_CLOSE = datetime.time(16, 0)
BAR_ORIGIN = "2024-01-01 09:30:00"  # 4시간봉 경계(현지시각): 09:30~13:30, 13:30~16:00
MIN_4H_BARS = int(os.environ.get("US_MIN_4H_BARS", "100"))  # RSI 수렴을 위한 최소 4시간봉 개수
BACKFILL_DAYS = 100  # 신규 종목 백필 구간(달력일)
BACKFILL_LIMIT = int(os.environ.get("US_BACKFILL_LIMIT", "8"))  # 실행당 신규 종목 백필 한도(해외는 호출이 느림)
NMIN = int(os.environ.get("KIS_US_NMIN", "1"))  # 요청 분봉 단위. 1이 가장 안전하고, 키우면 호출 수가 줄어든다
INCLUDE_FORMING_BAR = True  # 진행 중인 4시간봉도 RSI에 반영(HTS 화면·실시간 알림 기준)
SEED_MAX_FAILS = 3  # 시드(yfinance) 연속 실패가 이 횟수에 닿으면 이번 실행에서는 더 시도하지 않는다
NY = ZoneInfo("America/New_York")

class USAmericaRSIBot:
    def __init__(self, token, chat_id, kis):
        self.token = token
        self.chat_id = chat_id
        self.kis = kis
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.state = self.load_state()
        self.cache = BarCache(CACHE_FILE)
        self.backfill_budget = BACKFILL_LIMIT
        self.seed_fails = 0

    def get_session_date(self):
        kst_now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        session_time = kst_now - datetime.timedelta(hours=12)
        return session_time.strftime('%Y-%m-%d')

    def load_state(self):
        session_date = self.get_session_date()
        default_state = {"date": session_date, "signal_count": 0, "summary_sent": False, "alerted": []}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") != session_date:
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

    def send_telegram_alert(self, name, ticker, rsi_val, close_p, check_time):
        url_link = f"https://finance.yahoo.com/quote/{ticker}"
        self.state["signal_count"] = self.state.get("signal_count", 0) + 1
        self.save_state()

        message = (
            f"🚨 <b>🇺🇸 [미국장 4H RSI {int(RSI_THRESHOLD)} 이하 감지]</b>\n\n"
            f"• <b>종목명:</b> <a href='{url_link}'>{name}</a> (<code>{ticker}</code>)\n"
            f"• <b>4시간봉 RSI:</b> <code>{rsi_val:.2f}</code>\n"
            f"• <b>현재가:</b> ${close_p:,.2f}\n"
            f"• <b>기준 시간:</b> {check_time}"
        )
        requests.post(self.api_url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})

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
        )
        requests.post(self.api_url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True})

    def get_us_target_stocks(self):
        base_stocks = {
            "SPY": "S&P 500 ETF", "QQQ": "나스닥 100 ETF", "DIA": "다우존스 ETF",
            "TQQQ": "나스닥 3배", "SQQQ": "나스닥 인버스 3배", "QLD": "나스닥 2배",
            "UPRO": "S&P500 3배", "SOXX": "반도체 ETF", "SOXL": "반도체 3배",
            "SOXS": "반도체 인버스 3배", "USD": "반도체 2배", "TLT": "20년물 국채",
            "TMF": "국채 3배", "TSLL": "테슬라 2배", "CONL": "코인베이스 2배",
            "NVDL": "엔비디아 2배", "FNGU": "빅테크 3배", "TZA": "중소형주 인버스 3배",
            "BOIL": "천연가스 2배", "SCHD": "미국 배당성장 ETF",
            "AAPL": "애플", "NVDA": "엔비디아", "MSFT": "마이크로소프트",
            "GOOGL": "알파벳(구글)", "AMZN": "아마존", "META": "메타", "TSLA": "테슬라",
            "AVGO": "브로드컴", "TSM": "TSMC", "AMD": "AMD", "ASML": "ASML",
            "QCOM": "퀄컴", "MU": "마이크론", "INTC": "인텔", "ARM": "ARM 홀딩스",
            "PLTR": "팔란티어", "PANW": "팔로알토", "ADBE": "어도비", "SMCI": "슈퍼마이크로",
            "COIN": "코인베이스", "MSTR": "마이크로스트래티지", "HOOD": "로빈후드", "NFLX": "넷플릭스", 
            "DDOG": "데이터독", "NET": "클라우드플레어", "JPM": "JP모건", "BRK-B": "버크셔 해서웨이",
            "LLY": "일라이릴리", "JNJ": "존슨앤드존슨", "PEP": "펩시코", "MCD": "맥도날드", 
            "WMT": "월마트", "COST": "코스트코", "KO": "코카콜라",
        }

        my_favorites = {
        }

        base_stocks.update(my_favorites)
        return base_stocks

    def fetch_us_4h_rsi(self, ticker, now, today_str, period=14):
        """now: 미국 동부 현지 시각(naive). 완성된 4시간봉은 캐시, 진행 중 봉은 매번 새로 받는다."""
        entry = self.cache.entry(ticker)
        if entry.get("excd") == "":
            return None, None  # KIS에서 찾지 못한 종목(캐시 만료 전까지 재조회하지 않음)

        hist = self.cache.closes(ticker)
        if hist.empty:
            if self.backfill_budget <= 0:
                return None, None  # 이번 실행의 백필 한도 초과 → 다음 실행에서 처리
            self.backfill_budget -= 1
            start = datetime.datetime.combine((now - datetime.timedelta(days=BACKFILL_DAYS)).date(), US_SESSION_OPEN)
        else:
            start = (hist.index[-1] + pd.Timedelta(hours=4)).to_pydatetime()  # 첫 미수집 봉 시작

        excd, symb = entry.get("excd"), entry.get("symb")
        if not excd:
            found = self.kis.resolve_us_symbol(ticker)
            if not found:
                self.cache.update(ticker, pd.Series(dtype=float), today_str, excd="", symb="")
                print(f" [거래소 미확인] {ticker}: KIS에서 조회되지 않아 건너뜁니다.")
                return None, None
            excd, symb = found

        last_price = None
        forming = pd.Series(dtype=float)
        if start <= now:
            df = self.kis.get_us_minute_candles(excd, symb, start, now, NMIN)
            if len(df):
                # 정규장(09:30~16:00)만 사용. 프리/애프터마켓 봉은 제외한다.
                df = df[(df.index.time >= US_SESSION_OPEN) & (df.index.time < US_SESSION_CLOSE)]
            if len(df):
                complete, forming = split_complete(resample_4h_close(df, BAR_ORIGIN), now, US_SESSION_CLOSE)
                hist = complete if hist.empty else pd.concat([hist, complete])
                hist = hist[~hist.index.duplicated(keep="last")].sort_index()
                last_price = float(df["close"].iloc[-1])

        seeded = bool(entry.get("seeded"))
        if not seeded and len(hist) and len(hist) < MIN_4H_BARS and self.seed_fails < SEED_MAX_FAILS:
            try:
                seed = fetch_us_4h_seed(ticker, now, US_SESSION_CLOSE)
                older = seed[seed.index < hist.index[0]]  # 겹치는 구간은 KIS 값을 우선한다
                hist = pd.concat([older, hist]).sort_index()
                seeded = True
                self.seed_fails = 0
                print(f" [이력 시드] {ticker}: yfinance 과거 봉 {len(older)}개 추가 → {len(hist)}개")
            except Exception as e:
                self.seed_fails += 1
                print(f" [시드 실패] {ticker}: {e}")

        self.cache.update(ticker, hist, today_str, excd=excd, symb=symb, seeded=seeded)

        series = pd.concat([hist, forming]) if INCLUDE_FORMING_BAR and len(forming) else hist
        if len(series) < MIN_4H_BARS:
            print(f" [이력 부족] {ticker}: 4시간봉 {len(series)}개 (최소 {MIN_4H_BARS})")
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

        session_time = kst_now - datetime.timedelta(hours=12)
        nyse_holidays = holidays.NYSE()

        if session_time.weekday() >= 5 or session_time.date() in nyse_holidays:
            print(f" [휴장일] 미국 현지 주말 또는 공휴일이므로 스캐너를 실행하지 않습니다. ({check_time_str})")
            return

        print(f" [🇺🇸 미국장 스캐너 실행] KST 시간: {check_time_str}")

        # 💡 겨울철 1시간 누락을 막기 위한 '21' 시간대 추가
        if utc_hour in [13, 14, 15, 16, 17, 18, 19, 20, 21]:
            self.kis.issue_token()  # 실패하면 예외로 워크플로를 실패시켜 알 수 있게 한다
            us_stocks = self.get_us_target_stocks()
            now = datetime.datetime.now(NY).replace(tzinfo=None)
            failed = skipped = 0
            try:
                for ticker, name in us_stocks.items():
                    try:
                        rsi, close_p = self.fetch_us_4h_rsi(ticker, now, date_str)
                        if rsi is None:
                            skipped += 1
                        elif rsi <= RSI_THRESHOLD and ticker not in self.state.get("alerted", []):
                            self.send_telegram_alert(name, ticker, rsi, close_p, check_time_str)
                            self.state["alerted"].append(ticker)
                            self.save_state()
                    except Exception as e:
                        failed += 1
                        print(f" [조회 실패] {name}({ticker}): {e}")
            finally:
                self.cache.prune(pd.Timestamp(date_str))
                self.cache.save()  # 중간에 끊겨도 백필 진행분을 보존
            print(f" [스캔 완료] 대상 {len(us_stocks)}종목, 데이터 부족/백필 대기 {skipped}종목, 실패 {failed}종목")

        current_month = datetime.datetime.utcnow().month
        is_dst = 3 <= current_month <= 11
        summary_hours = [20, 21, 22] if is_dst else [21, 22, 23]
        if utc_hour in summary_hours and not self.state["summary_sent"]:
            self.send_daily_summary(date_str, self.state.get("signal_count", 0))

if __name__ == "__main__":
    kis = KISClient(KIS_APP_KEY, KIS_APP_SECRET)
    bot = USAmericaRSIBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, kis)
    bot.run()
