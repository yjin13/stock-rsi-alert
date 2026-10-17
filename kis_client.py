import os
import json
import time
import datetime
import requests
import pandas as pd

DEFAULT_BASE_URL = "https://openapi.koreainvestment.com:9443"  # 모의투자: https://openapivts.koreainvestment.com:29443
TOKEN_FILE = os.path.expanduser(os.environ.get("KIS_TOKEN_FILE", "~/.kis_token.json"))  # 저장소 밖에 둔다
KR_MINUTE_TR_ID = "FHKST03010230"  # 국내 주식일별분봉조회 (1회 최대 120건, 과거 최대 1년)
US_MINUTE_TR_ID = "HHDFS76950200"  # 해외주식분봉조회 (1회 최대 120건)
US_EXCHANGES = ("NAS", "NYS", "AMS")  # 나스닥, 뉴욕, 아멕스(NYSE Arca 등)
SESSION_OPEN = datetime.time(9, 0)
SESSION_CLOSE = datetime.time(15, 30)
KR_CALL_DELAY = 0.06  # 국내 실전 초당 20회 제한 대비
US_CALL_DELAY = float(os.environ.get("KIS_US_CALL_DELAY", "0.3"))  # 해외는 더 엄격하다는 보고가 있어 여유를 둔다


def _kst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)


class KISClient:
    def __init__(self, app_key, app_secret, base_url=None):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = (base_url or os.environ.get("KIS_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.token = None

    def issue_token(self):
        """토큰 파일이 유효하면 재사용한다(재발급 제한·알림톡 방지). 만료 10분 전부터는 새로 받는다."""
        cached = self._load_token()
        if cached:
            self.token = cached
            return

        res = requests.post(
            f"{self.base_url}/oauth2/tokenP",
            headers={"Content-Type": "application/json"},
            json={"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret},
            timeout=10,
        )
        data = res.json()
        if res.status_code != 200 or not data.get("access_token"):
            raise RuntimeError(f"KIS 토큰 발급 실패: {data.get('error_description') or data}")
        self.token = data["access_token"]
        self._save_token(data.get("access_token_token_expired"))

    def _load_token(self):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            expires = datetime.datetime.strptime(saved["expires"], "%Y-%m-%d %H:%M:%S")
            if expires - _kst_now() > datetime.timedelta(minutes=10):
                return saved["token"]
        except Exception:
            pass
        return None

    def _save_token(self, expires_str):
        try:
            # 만료시각이 없으면 보수적으로 6시간 뒤로 본다
            expires = expires_str or (_kst_now() + datetime.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump({"token": self.token, "expires": expires}, f)
            os.chmod(TOKEN_FILE, 0o600)
        except Exception:
            pass

    def _get(self, path, tr_id, params, retries=3):
        if self.token is None:
            self.issue_token()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        for attempt in range(retries):
            res = requests.get(f"{self.base_url}{path}", headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("msg_cd") == "EGW00201":  # 초당 호출 제한 초과
                time.sleep(1 + attempt)
                continue
            if res.status_code != 200 or data.get("rt_cd") != "0":
                raise RuntimeError(f"KIS 조회 실패({tr_id}): {data.get('msg_cd')} {data.get('msg1')}")
            return data
        raise RuntimeError(f"KIS 호출 제한 초과({tr_id}): 재시도 실패")

    # ---------------------------------------------------------------- 국내
    def get_minute_candles(self, code, start, end):
        """국내 1분봉을 최신→과거 순으로 120건씩 받아 [start, end] 구간만 오래된 순으로 반환."""
        rows = []
        cursor = end
        for _ in range(500):  # 무한 루프 방지
            data = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
                KR_MINUTE_TR_ID,
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": cursor.strftime("%Y%m%d"),
                    "FID_INPUT_HOUR_1": cursor.strftime("%H%M%S"),
                    "FID_PW_DATA_INCU_YN": "Y",
                    "FID_FAKE_TICK_INCU_YN": "",
                },
            )
            time.sleep(KR_CALL_DELAY)
            page = [r for r in (data.get("output2") or []) if r.get("stck_bsop_date") and r.get("stck_cntg_hour")]

            if page:
                rows.extend(page)
                oldest = min(self._kr_time(r) for r in page)
                if oldest <= start:
                    break
                cursor = oldest - datetime.timedelta(minutes=1)
            else:
                # 휴장일 등으로 비면 전 거래일 마감 시각으로 한 칸 이동
                prev_day = cursor.date() - datetime.timedelta(days=1)
                cursor = datetime.datetime.combine(prev_day, SESSION_CLOSE)
                if cursor <= start:
                    break
                continue

            # 장 시작 이전으로 내려가면 전일 마감으로 이동(응답이 일 경계를 넘지 않는 경우 대비)
            if cursor.time() < SESSION_OPEN:
                prev_day = cursor.date() - datetime.timedelta(days=1)
                cursor = datetime.datetime.combine(prev_day, SESSION_CLOSE)

        return self._frame(
            [self._kr_time(r) for r in rows],
            [(r["stck_oprc"], r["stck_hgpr"], r["stck_lwpr"], r["stck_prpr"], r["cntg_vol"]) for r in rows],
            start, end,
        )

    @staticmethod
    def _kr_time(row):
        return datetime.datetime.strptime(row["stck_bsop_date"] + row["stck_cntg_hour"], "%Y%m%d%H%M%S")

    # ---------------------------------------------------------------- 해외
    def _us_params(self, excd, symb, nmin, nxt, keyb, nrec=120):
        return {
            "AUTH": "", "EXCD": excd, "SYMB": symb, "NMIN": str(nmin), "PINC": "1",
            "NEXT": nxt, "NREC": str(nrec), "FILL": "", "KEYB": keyb,
        }

    def resolve_us_symbol(self, ticker):
        """티커가 상장된 KIS 거래소 코드와 심볼 표기를 찾는다. 못 찾으면 None. (결과는 호출 측에서 캐시)"""
        symbols = [ticker]
        if "-" in ticker:  # BRK-B 같은 클래스 주식은 표기가 다를 수 있어 후보를 둔다
            symbols += [ticker.replace("-", "."), ticker.replace("-", "/")]
        for symb in symbols:
            for excd in US_EXCHANGES:
                try:
                    data = self._get("/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice",
                                     US_MINUTE_TR_ID, self._us_params(excd, symb, 1, "", "", nrec=1))
                except RuntimeError:
                    continue
                finally:
                    time.sleep(US_CALL_DELAY)
                if data.get("output2"):
                    return excd, symb
        return None

    def get_us_minute_candles(self, excd, symb, start, end, nmin=1):
        """해외 분봉(현지시각 기준)을 최신→과거 순으로 120건씩 받아 [start, end] 구간만 오래된 순으로 반환."""
        rows = []
        nxt, keyb = "", ""
        for _ in range(600):  # 무한 루프 방지
            data = self._get("/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice",
                             US_MINUTE_TR_ID, self._us_params(excd, symb, nmin, nxt, keyb))
            time.sleep(US_CALL_DELAY)
            page = [r for r in (data.get("output2") or []) if r.get("xymd") and r.get("xhms")]
            if not page:
                break  # PINC=1이면 전일 이전까지 이어서 오므로 빈 응답은 보관 이력의 끝
            rows.extend(page)
            oldest = min(self._us_time(r) for r in page)
            if oldest <= start:
                break
            nxt = "1"
            keyb = (oldest - datetime.timedelta(minutes=nmin)).strftime("%Y%m%d%H%M%S")

        return self._frame(
            [self._us_time(r) for r in rows],
            [(r["open"], r["high"], r["low"], r["last"], r["evol"]) for r in rows],
            start, end,
        )

    @staticmethod
    def _us_time(row):
        return datetime.datetime.strptime(row["xymd"] + row["xhms"], "%Y%m%d%H%M%S")

    # ---------------------------------------------------------------- 공통
    @staticmethod
    def _frame(times, values, start, end):
        if not times:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(values, columns=["open", "high", "low", "close", "volume"]).astype(float)
        df.index = pd.DatetimeIndex(times, name="datetime")
        df = df[~df.index.duplicated()].sort_index()
        return df[(df.index >= start) & (df.index <= end)]
