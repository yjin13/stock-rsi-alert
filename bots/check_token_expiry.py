import os
import html
import json
import datetime
import requests
from lib.rsi_common import DATA_DIR

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "본인의_BOT_TOKEN_입력")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "본인의_CHAT_ID_입력")
EXPIRY_FILE = os.path.join(DATA_DIR, "token_expiry.json")  # 갱신할 때 expires 날짜를 새 만료일로 고친다
STATE_FILE = os.path.join(DATA_DIR, "expiry_state.json")  # 대상별 마지막 알림 날짜(하루 1회 제한용)
WARN_DAYS = 7  # 만료 며칠 전부터 알릴지
NOTIFY_FROM_HOUR_KST = 9  # 새벽 알림을 피하려고 이 시각(KST) 이후 첫 실행에서 발송


def kst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build_notices(tokens, state, now):
    """오늘 보내야 할 (대상 이름, 메시지) 목록. 만료 WARN_DAYS일 전부터 만료 후 갱신 전까지 매일 1회."""
    if now.hour < NOTIFY_FROM_HOUR_KST:
        return []

    today = now.date()
    notices = []
    for t in tokens:
        if state.get(t["name"]) == today.isoformat():
            continue
        days_left = (datetime.date.fromisoformat(t["expires"]) - today).days
        if days_left > WARN_DAYS:
            continue

        if days_left > 0:
            status = f"D-{days_left} (만료까지 {days_left}일)"
        elif days_left == 0:
            status = "오늘 만료"
        else:
            status = f"만료됨 ({-days_left}일 경과) — 스캔이 멈췄을 수 있습니다"

        message = (
            f"🔑 <b>[토큰 만료 임박]</b>\n\n"
            f"• <b>대상:</b> {html.escape(t['name'])}\n"
            f"• <b>만료일:</b> {t['expires']}\n"
            f"• <b>상태:</b> {status}\n\n"
            f"👉 <b>갱신 방법:</b> {html.escape(t.get('renew', '-'))}\n"
            f"<i>갱신 후 data/token_expiry.json 의 expires 날짜를 새 만료일로 수정하세요. (갱신 전까지 매일 알립니다)</i>"
        )
        notices.append((t["name"], message))
    return notices


def main():
    tokens = load_json(EXPIRY_FILE, [])
    state = load_json(STATE_FILE, {})
    now = kst_now()
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    sent = 0
    for name, message in build_notices(tokens, state, now):
        try:
            res = requests.post(api_url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
            if res.status_code == 200:
                state[name] = now.date().isoformat()  # 전송 성공한 경우만 기록 → 실패하면 다음 실행에서 재시도
                sent += 1
            else:
                print(f" [만료 알림 전송 실패] {name}: HTTP {res.status_code}")
        except Exception as e:
            print(f" [만료 알림 전송 실패] {name}: {e}")

    if sent:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
    print(f" [토큰 만료 확인] 대상 {len(tokens)}건, 오늘 알림 {sent}건")


if __name__ == "__main__":
    main()  # 알림 실패가 스캐너 실행을 막지 않도록 항상 정상 종료한다
