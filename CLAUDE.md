# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

한국장(KOSPI/KOSDAQ 거래량 상위 종목)과 미국장(지정 종목·ETF)의 **4시간봉 RSI가 임계값(30) 이하로 떨어지면 텔레그램으로 알림**을 보내는 스캐너입니다. 별도 서버 없이 GitHub Actions 크론으로 30분마다 실행됩니다. 시세는 두 시장 모두 **한국투자증권(KIS) Open API**의 분봉으로 받습니다.

### 디렉터리 구성 (기능별)

- `bots/` — 워크플로가 직접 실행하는 텔레그램 알림 스크립트. 저장소 루트에서 `python -m bots.<이름>`으로 실행합니다.
  - `rsi_kr_bot.py` — 한국장. 종목 목록은 네이버 금융 거래량 상위 페이지에서 긁고, 시세는 KIS 국내 1분봉.
  - `rsi_us_bot.py` — 미국장. 하드코딩된 종목 목록, 시세는 KIS 해외 분봉(현지 시각 기준, 정규장 09:30~16:00만 사용).
  - `check_token_expiry.py` — `data/token_expiry.json`에 적힌 KIS 키·GitHub 토큰의 만료일을 보고, **만료 7일 전부터(만료 후 갱신 전까지) 하루 1번** 텔레그램으로 알립니다. 워크플로 첫 스텝(`continue-on-error`)으로 돌아 스캐너가 실패해도 알림은 나갑니다(KST 09시 이후 첫 실행에서 발송, 전송 실패 시 다음 실행에서 재시도).
- `lib/` — 봇들이 공유하는 라이브러리.
  - `kis_client.py` — KIS 토큰 발급(파일 캐시 재사용), 국내 `주식일별분봉조회`(FHKST03010230), 해외 `해외주식분봉조회`(HHDFS76950200) 페이지네이션, 해외 티커→거래소 코드 탐색.
  - `rsi_common.py` — Wilder RSI, 4시간봉 묶기, 완성/진행 중 봉 분리, `BarCache`(JSON 캐시), 데이터 경로(`DATA_DIR`).
- `data/` — 상태·캐시·로그·설정 JSON. **`token_expiry.json`만 사람이 편집**하고 나머지는 워크플로가 커밋합니다(로컬에서 봇을 실행하면 이 파일들이 바뀝니다).
  - `kr_state.json`, `us_state.json` — 당일 알림 중복 방지·일일 요약 발송 여부.
  - `kr_4h_cache.json`, `us_4h_cache.json` — 종목별 완성된 4시간봉 종가 캐시(US는 KIS 거래소 코드/심볼 포함).
  - `expiry_state.json` — 토큰 만료 알림의 마지막 발송 날짜.
  - `scanner_log.txt` — 실행 로그(최근 100줄 유지).
  - `token_expiry.json` — 토큰 만료일 설정(`name`/`expires`/`renew`).
- `.github/workflows/rsi_scanner.yml` — 세 스크립트를 순서대로 돌린 뒤 `data/` 안의 로그·상태·캐시를 봇 계정으로 커밋·푸시합니다. `concurrency`로 실행이 겹치지 않게 순차 처리합니다. 실행 트리거는 아래 "스케줄링" 참고.

## 명령어

의존성 설치 (CI와 동일):
```
pip install pandas numpy requests beautifulsoup4 holidays
```

실행 (저장소 루트에서. 환경변수가 없으면 전송/인증이 실패합니다):
```
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... KIS_APP_KEY=... KIS_APP_SECRET=...
python -m bots.rsi_kr_bot
python -m bots.rsi_us_bot
```

선택 환경변수: `RSI_DATA_DIR`(상태·캐시·설정 폴더, 기본 `data/`), `KIS_BASE_URL`(모의투자 도메인 등), `KIS_TOKEN_FILE`(기본 `~/.kis_token.json`), `KR_BACKFILL_LIMIT`(기본 20)/`US_BACKFILL_LIMIT`(기본 8) 실행당 신규 종목 백필 한도, `KIS_US_NMIN`(해외 요청 분봉 단위, 기본 1), `KIS_US_CALL_DELAY`(해외 호출 간격 초, 기본 0.3), `US_MIN_4H_BARS`(기본 100).

테스트·린터·빌드 설정은 저장소에 없습니다. 검증은 `KISClient`를 가짜 객체로 바꿔 `KoreaRSIBot.fetch_kr_4h_rsi` / `USAmericaRSIBot.fetch_us_4h_rsi`를 직접 호출하는 식으로 합니다(상태·캐시 파일이 `data/`에 만들어지니 `RSI_DATA_DIR`을 임시 폴더로 지정하고, `token_expiry.json`도 그 폴더에 두어야 합니다).

## 스케줄링

- **외부 스케줄러(주 트리거): [cron-job.org](https://cron-job.org)** 가 매 30분마다(정각·30분) GitHub API로 `workflow_dispatch`를 호출해 워크플로를 실행합니다. GitHub Actions 자체 `schedule`은 부하 때문에 수 분~수십 분 지연되거나 건너뛰는 일이 있어, 정각 오차를 줄이려고 외부에서만 깨웁니다.
- 호출 형식(cron-job.org 작업 설정): `POST https://api.github.com/repos/yjin13/stock-rsi-alert/actions/workflows/rsi_scanner.yml/dispatches`, 헤더 `Authorization: Bearer <GitHub 토큰>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, 본문 `{"ref":"main"}`. 성공하면 `204`가 옵니다.
- **토큰은 cron-job.org 설정에만 있고 저장소에는 없습니다.** 코드·문서·시크릿에 토큰 값을 적지 마세요. 가능하면 이 저장소 하나에 `Actions: Read and write` 권한만 준 fine-grained 토큰을 쓰고, 만료일을 정해 갱신합니다(classic 토큰이면 `workflow` 스코프 필요). 토큰이 만료·폐기되면 호출이 `401/403`으로 실패하고 스캔이 멈추니 cron-job.org의 실행 이력/실패 알림을 확인하세요.
- 워크플로에는 자체 `schedule`이 **없습니다.** 트리거는 `workflow_dispatch`(cron-job.org 호출 + 수동 실행) 하나뿐이라, cron-job.org가 멈추거나 토큰이 만료되면 스캔이 전혀 돌지 않습니다. 겹쳐 실행되는 경우는 `concurrency`(`cancel-in-progress: false`)가 순차 처리합니다.
- 스캔 시간대 판단은 실행 시각의 UTC '시(hour)'만 보므로 정각/30분 호출로 바뀌어도 동작 로직은 그대로입니다.
- **권장 호출 시간대(cron-job.org 시간대 `Asia/Seoul`, 매시 0분·30분):** KST 0~6시, 9~16시, 22~23시. 봇이 스캔·요약을 하는 구간(KR: UTC 0~9시 = KST 9~18시, US: UTC 13~23시 = KST 22~08시)에서 서머타임 여부와 무관하게 장 시작부터 마감 후 요약까지를 덮고, 그 밖의 시간은 봇이 아무것도 하지 않으므로 호출하지 않습니다. cron 식으로는 `0,30 0-6,9-16,22-23 * * *` (매일, 주말·휴장일은 봇이 스스로 건너뜀)이고, 요일까지 줄이면 KR `0,30 9-16 * * 1-5`, US `0,30 22-23 * * 1-5` + `0,30 0-6 * * 2-6`입니다(US는 KST 새벽이 전날 미국 세션이라 화~토).

## 구조에서 여러 파일을 읽어야 보이는 부분

- **4시간봉은 캐시 + 증분 갱신입니다.** KIS 분봉은 1분 단위(해외는 `NMIN`)이고 RSI 수렴에 4시간봉 100개 이상이 필요해서(1분봉 약 2만 개, 종목당 약 160~230회 호출), 완성된 4시간봉 종가만 JSON 캐시에 저장하고 이후엔 마지막 완성 봉 이후 구간만 받습니다. 신규 종목은 최근 `BACKFILL_DAYS`(100일)를 백필하며 실행당 한도까지만 처리하고 나머지는 다음 실행으로 넘어갑니다(처음 시딩할 때 `workflow_dispatch`를 여러 번 돌려야 합니다).
- **4시간봉 = 240분봉**입니다. 장 시작 시각부터 240분 단위로 1분봉을 묶고(`resample_4h_close`, `origin`=장 시작), 날짜가 바뀌어도 봉을 합치지 않습니다. 하루에 봉이 2개이고 둘째 봉은 장 마감까지의 짧은 봉입니다: KR 09:00~13:00, 13:00~15:30 / US 현지 09:30~13:30, 13:30~16:00. HTS의 240분봉과 같은 경계인지는 키로 실측해 대조해야 합니다.
- **RSI에는 진행 중인 4시간봉도 포함합니다**(`INCLUDE_FORMING_BAR`). HTS 화면·실시간 알림과 맞추기 위한 것이고, 캐시에는 완성된 봉만 저장합니다. 봉 종료는 `min(시작+4h, 장 마감)`입니다.
- **RSI는 Wilder 평활**(`ewm(alpha=1/14, adjust=False)`)이고 이력이 짧으면 값이 흔들려 `MIN_4H_BARS`(100) 미만 종목은 건너뜁니다.
- **미국장 시각은 두 종류입니다.** 봉 데이터와 4시간봉은 미국 동부 현지 시각(`America/New_York`, 응답의 `xymd/xhms`)을 쓰고, 스캔 시간대·휴장일·세션 날짜 판단은 기존대로 UTC/`KST-12h` 기준입니다.
- **미국 티커→거래소는 첫 조회 때 `NAS/NYS/AMS` 순으로 탐색해 캐시에 저장**합니다(`BRK-B`는 `.`/`/` 표기도 시도). 찾지 못하면 `excd: ""`로 기록해 캐시 만료(14일) 전까지 재조회하지 않습니다.
- **실행 시각으로 동작이 갈립니다.** `run()`은 UTC 시각으로 분기합니다. KR은 UTC 0~7시에 스캔, UTC 7~9시에 일일 요약. US는 UTC 13~21시에 스캔, 요약 시각은 DST 여부에 따라 `[20,21,22]` 또는 `[21,22,23]`. 시간대를 바꾸면 워크플로 cron과 함께 봐야 합니다.
- **휴장일 판단은 현지 시각 기준입니다.** KR은 KST 날짜로 `holidays.KR()`, US는 `KST - 12h`로 `holidays.NYSE()`를 확인합니다.
- **하루 단위 상태 관리.** `state["date"]`가 오늘과 다르면 초기화(US는 `KST - 12h` 세션 날짜). 같은 종목은 하루 한 번만 알림(`alerted`).
- **KIS 토큰**은 24시간 유효, 6시간 내 재요청 시 같은 토큰이 오고 발급마다 알림톡이 갑니다. 그래서 `~/.kis_token.json`(저장소 밖, `.gitignore` 대상)에 저장하고 워크플로의 `actions/cache`로 실행 간 유지합니다. 토큰 파일을 저장소 안에 두지 마세요(`git add -A`로 커밋됩니다).
- **KIS 응답 가정(키로 실측 필요):** 국내 분봉이 1분 단위인지, 국내 `stck_cntg_hour`/해외 `xhms`가 봉 시작·종료 중 어느 쪽인지, 해외 과거 분봉 보관 기간, 해외 호출 제한은 공식 샘플 코드·2차 자료 기준입니다. 해외 이력이 짧으면 `[이력 부족]` 로그가 남습니다.
- **에러 처리:** 종목별 예외는 로그(`[조회 실패]`)로 남기고 계속 진행합니다. 토큰 발급 실패는 예외로 올려 워크플로를 실패시킵니다. 상태 저장 실패는 조용히 무시됩니다(`save_state`).
- **두 봇의 `load_state`/`save_state`/텔레그램 전송부는 아직 복붙 상태**입니다. 한쪽을 고칠 때 다른 쪽도 확인하세요.

## 토큰·키 만료 관리 (발급 후 1년)

한국투자증권 Open API 키와 GitHub 토큰은 **발급일로부터 1년 뒤 만료**됩니다(소유자 확인 기준). 만료되면 스캔이 조용히 멈추므로, 발급일을 아래에 적어 두고 만료 2주 전에 미리 갱신하세요.

| 대상 | 발급일 | 만료일(발급+1년) | 사용처 |
|---|---|---|---|
| KIS App Key / App Secret | 2026-10-17 | 2027-10-17 | GitHub Secrets `KIS_APP_KEY`, `KIS_APP_SECRET` |
| GitHub 토큰(워크플로 실행용) | 2026-10-17 | 2027-10-17 | cron-job.org 작업의 `Authorization: Bearer ...` 헤더 |

**자동 알림:** 만료일은 `data/token_expiry.json`(대상별 `name`/`expires`/`renew`)에서 관리하고, `bots/check_token_expiry.py`가 만료 7일 전부터 매일 한 번 텔레그램으로 알립니다. **키·토큰을 갱신하면 반드시 `data/token_expiry.json`의 `expires`를 새 만료일로 고치고 위 표도 같이 고치세요.** 그래야 알림이 멈춥니다. 대상을 늘리려면 JSON에 항목을 추가하면 됩니다.

### KIS App Key/Secret 만료 시
- **증상:** 워크플로가 `KIS 토큰 발급 실패`로 실패(Actions 탭에 빨간 ✗)하고 알림·일일 요약이 모두 끊깁니다. 코드 문제가 아니라 키 문제입니다.
- **수정 위치:** 코드 변경 없음.
  1. KIS Developers(apiportal.koreainvestment.com)에서 App Key/Secret을 재발급(또는 서비스 재신청).
  2. 저장소 **Settings → Secrets and variables → Actions**에서 `KIS_APP_KEY`, `KIS_APP_SECRET` 값을 새 값으로 교체(이름은 그대로).
  3. 교체 후에도 `invalid token` 류 오류가 나면, 이전 키로 받은 접근토큰이 `actions/cache`에 남아 최대 24시간 재사용되는 경우입니다. **Actions → Caches**에서 `kis-token-*` 캐시를 삭제하거나, `rsi_scanner.yml`의 `kis-token-` 접두어를 `kis-token-v2-`처럼 바꿔 캐시를 무효화하세요(`key`와 `restore-keys` 둘 다).
  4. `workflow_dispatch`로 수동 실행해 성공 여부 확인.
  5. `data/token_expiry.json`의 "KIS App Key/Secret" `expires`를 새 만료일로 수정(만료 알림 중지).
- 모의투자 도메인을 쓰는 경우 `KIS_BASE_URL`도 키 종류(실전/모의)와 맞아야 합니다.

### GitHub 토큰 만료 시
- **증상:** cron-job.org 실행 이력에 `401`/`403`이 찍히고, Actions 탭에 새 실행이 생기지 않으며, 텔레그램 알림·요약이 아예 오지 않습니다(자체 `schedule`이 없어 대체 트리거가 없음).
- **수정 위치:** 저장소 코드·Secrets는 건드리지 않습니다.
  1. GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens**에서 새 토큰 생성: 이 저장소만 선택, 권한 `Actions: Read and write`, 만료 1년.
  2. **cron-job.org**의 모든 호출 작업(시간대별로 나눴다면 전부)에서 `Authorization: Bearer <새 토큰>` 헤더 값을 교체하고 저장.
  3. 작업의 Test run으로 `204` 응답과 Actions 탭의 새 실행을 확인.
  4. 확인 후 만료된/이전 토큰은 GitHub에서 삭제.
  5. `data/token_expiry.json`의 "GitHub 토큰 (cron-job.org)" `expires`를 새 만료일로 수정(만료 알림 중지).

## 주의

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `KIS_APP_KEY`, `KIS_APP_SECRET`는 GitHub Secrets에서 주입됩니다. 코드에 값을 넣지 마세요.
- 워크플로가 `git add -A`로 커밋하므로, 로컬 작업 중 만든 임시 파일이 자동 커밋될 수 있습니다.
- 두 봇은 워크플로의 별도 스텝으로 순차 실행됩니다. 한국장 스크립트가 예외로 종료하면 기본 설정상 뒤의 미국장 스텝과 로그 커밋 스텝이 실행되지 않습니다.
