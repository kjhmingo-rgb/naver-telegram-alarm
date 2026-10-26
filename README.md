# 네이버 캘린더 → 텔레그램 알림

- 일정 시작 **30분 전** 텔레그램 알림
- 매일 **아침 8시** 오늘 일정 요약
- GitHub Actions에서 10분마다 자동 실행 (PC 꺼져 있어도 동작)

---

## 1. 네이버 애플리케이션 비밀번호 만들기

네이버 → 내정보 → 보안설정 → **2단계 인증** 켜기 → 관리하기 → **애플리케이션 비밀번호 관리**에서 하나 생성해서 복사해 두세요.
(평소 로그인 비밀번호와 별개라서, 나중에 언제든 삭제하면 바로 접근이 끊깁니다.)

## 2. 텔레그램 봇 만들기

1. 텔레그램에서 **@BotFather** 검색 → `/newbot` → 이름 정하기 → **봇 토큰** 복사
2. 방금 만든 봇과 대화방을 열고 아무 메시지나 하나 보내기 (예: `안녕`)
3. 브라우저에서 아래 주소 열기 (`<토큰>` 자리에 봇 토큰)
   `https://api.telegram.org/bot<토큰>/getUpdates`
4. 결과에서 `"chat":{"id": 123456789` 부분의 숫자가 **채팅 ID**

## 3. GitHub 저장소 만들기

1. GitHub에서 새 저장소 생성 → **Public 권장**
   (Public이면 Actions가 무료 무제한. 비밀번호·토큰은 Secrets에 들어가서 공개되지 않고, 저장소에는 일정 제목이 아닌 해시값만 저장됩니다.
   Private로 하면 10분마다 실행 시 월 무료 사용량 2,000분을 넘을 수 있어요.)
2. 이 폴더의 파일을 그대로 올리기 (`.github/workflows/notify.yml` 경로 유지 필수)
   - 웹에서 올릴 땐: **Add file → Upload files**에 폴더째 드래그

## 4. Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| 이름 | 값 |
|---|---|
| `NAVER_ID` | 네이버 아이디 (@naver.com 빼고) |
| `NAVER_APP_PASSWORD` | 1번에서 만든 애플리케이션 비밀번호 |
| `TELEGRAM_BOT_TOKEN` | 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 채팅 ID |

## 5. 테스트

저장소 → **Actions** 탭 → (처음이면 Actions 활성화 버튼 클릭) → **네이버 캘린더 알림** → **Run workflow** → 실행

텔레그램에 "✅ 연결 테스트 성공!"과 캘린더 목록, 오늘 일정이 오면 끝입니다. 이후엔 10분마다 자동으로 돌아갑니다.

---

## 설정 바꾸기 (선택)

**Settings → Secrets and variables → Actions → Variables 탭**에 추가

| 이름 | 설명 | 기본값 |
|---|---|---|
| `REMIND_MINUTES_BEFORE` | 일정 몇 분 전에 알릴지 | `30` |
| `DAILY_SUMMARY_HOUR` | 아침 요약 시각 (0~23, `-1`이면 끔) | `8` |
| `CALENDAR_NAMES` | 특정 캘린더만 (쉼표로 구분, 테스트 메시지에 나온 이름 그대로) | 전체 |

## 참고

- GitHub 스케줄은 몇 분씩 늦게 실행되는 경우가 있어요. 그래서 알림이 정확히 30분 전이 아니라 20~30분 전쯤 올 수 있습니다.
- 종일 일정은 개별 알림 없이 아침 요약에만 나옵니다.
- 실행이 실패하면 GitHub에서 메일로 알려줍니다. 대부분 Secrets 오타나 애플리케이션 비밀번호 삭제가 원인이에요.
- 그만 쓰고 싶으면 Actions 탭에서 워크플로를 **Disable** 하면 됩니다.
