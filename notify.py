"""
네이버 캘린더 → 텔레그램 알림

- 일정 시작 N분 전(기본 30분)에 텔레그램으로 알림
- 매일 아침 정해진 시각(기본 8시)에 오늘 일정 요약
- GitHub Actions에서 10분마다 실행되는 것을 전제로 함

공개 저장소에서도 안전하도록 로그에는 일정 제목/내용을 절대 출력하지 않습니다.
"""

import datetime as dt
import hashlib
import html
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import caldav
import recurring_ical_events
import requests

KST = ZoneInfo("Asia/Seoul")
CALDAV_URL = "https://caldav.calendar.naver.com"
STATE_FILE = Path("state/sent.json")
WEEKDAYS = "월화수목금토일"


def env(name, default=None, required=False):
    value = (os.environ.get(name) or "").strip()
    if not value:
        if required:
            sys.exit(f"[오류] 환경변수 {name} 가 설정되지 않았습니다. GitHub Secrets를 확인하세요.")
        return default
    return value


NAVER_ID = env("NAVER_ID", required=True)
NAVER_APP_PASSWORD = env("NAVER_APP_PASSWORD", required=True)
TG_TOKEN = env("TELEGRAM_BOT_TOKEN", required=True)
TG_CHAT_ID = env("TELEGRAM_CHAT_ID", required=True)

REMIND_MINUTES = int(env("REMIND_MINUTES_BEFORE", "30"))       # 일정 몇 분 전에 알릴지
SUMMARY_HOUR = int(env("DAILY_SUMMARY_HOUR", "8"))             # 아침 요약 시각 (-1이면 끔)
CALENDAR_NAMES = [c.strip() for c in env("CALENDAR_NAMES", "").split(",") if c.strip()]  # 비우면 전체


# ---------------------------------------------------------------- 텔레그램

def send_telegram(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={
                "chat_id": TG_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
    except requests.RequestException as e:
        # 토큰이 포함된 URL이 로그에 남지 않도록 예외 종류만 출력
        raise RuntimeError(f"텔레그램 전송 실패 ({type(e).__name__})") from None
    if r.status_code != 200:
        raise RuntimeError(f"텔레그램 전송 실패 (HTTP {r.status_code}): {r.text[:200]}")


# ---------------------------------------------------------------- 네이버 캘린더

def get_calendars():
    client = caldav.DAVClient(url=CALDAV_URL, username=NAVER_ID, password=NAVER_APP_PASSWORD)
    return client.principal().calendars()


def to_kst(value):
    """DTSTART 값을 (KST datetime, 종일여부)로 변환"""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=KST)
        return value.astimezone(KST), False
    return dt.datetime.combine(value, dt.time(0), KST), True


def fetch_events(start, end):
    events = {}
    for cal in get_calendars():
        name = cal.name or ""
        if CALENDAR_NAMES and name not in CALENDAR_NAMES:
            continue
        try:
            results = cal.search(start=start, end=end, event=True)
        except Exception as e:
            print(f"[경고] 캘린더 하나를 읽지 못했습니다 ({type(e).__name__})")
            continue
        for res in results:
            try:
                ical = res.icalendar_instance
                # 반복 일정은 직접 펼쳐서 실제 발생 일시를 구함
                for ev in recurring_ical_events.of(ical).between(start, end):
                    if ev.get("DTSTART") is None:
                        continue
                    start_kst, all_day = to_kst(ev.get("DTSTART").dt)
                    uid = str(ev.get("UID", ""))
                    key = hashlib.sha1(f"{uid}|{start_kst.isoformat()}".encode()).hexdigest()[:16]
                    events[key] = {
                        "key": key,
                        "title": str(ev.get("SUMMARY", "") or "(제목 없음)"),
                        "location": str(ev.get("LOCATION", "") or ""),
                        "start": start_kst,
                        "all_day": all_day,
                        "calendar": name,
                    }
            except Exception as e:
                print(f"[경고] 일정 하나를 해석하지 못했습니다 ({type(e).__name__})")
    return sorted(events.values(), key=lambda e: (not e["all_day"], e["start"]))


# ---------------------------------------------------------------- 상태 저장

def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"summary_date": "", "sent": {}}


def save_state(state, now):
    # 이틀 지난 기록은 정리
    cutoff = (now - dt.timedelta(days=2)).isoformat()
    state["sent"] = {k: v for k, v in state["sent"].items() if v >= cutoff}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------- 메시지

def fmt_day(d):
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def fmt_event_line(e):
    when = "종일" if e["all_day"] else e["start"].strftime("%H:%M")
    line = f"• <b>{when}</b>  {html.escape(e['title'])}"
    if e["location"]:
        line += f"\n   📍 {html.escape(e['location'])}"
    return line


def reminder_text(e, now):
    minutes = max(0, round((e["start"] - now).total_seconds() / 60))
    head = "⏰ 곧 시작해요" if minutes <= 1 else f"⏰ {minutes}분 후 일정"
    text = f"{head}\n\n<b>{html.escape(e['title'])}</b>\n🕒 {fmt_day(e['start'])} {e['start'].strftime('%H:%M')}"
    if e["location"]:
        text += f"\n📍 {html.escape(e['location'])}"
    return text


def summary_text(events, today):
    if not events:
        return f"☀️ {fmt_day(today)} 오늘은 등록된 일정이 없어요."
    lines = "\n".join(fmt_event_line(e) for e in events)
    return f"☀️ {fmt_day(today)} 오늘 일정 ({len(events)}개)\n\n{lines}"


# ---------------------------------------------------------------- 실행

def run_test():
    names = [c.name or "(이름 없음)" for c in get_calendars()]
    now = dt.datetime.now(KST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = fetch_events(start, start + dt.timedelta(days=1))
    cal_list = "\n".join(f"• {html.escape(n)}" for n in names) or "(없음)"
    send_telegram(
        "✅ 연결 테스트 성공!\n\n"
        f"<b>네이버 캘린더 목록</b>\n{cal_list}\n\n"
        f"설정: {REMIND_MINUTES}분 전 알림, "
        + (f"매일 {SUMMARY_HOUR}시 요약" if SUMMARY_HOUR >= 0 else "아침 요약 끔")
        + "\n\n" + summary_text(events, now)
    )
    print(f"테스트 완료: 캘린더 {len(names)}개, 오늘 일정 {len(events)}개")


def run():
    now = dt.datetime.now(KST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    fetch_end = max(today_start + dt.timedelta(days=1), now + dt.timedelta(minutes=REMIND_MINUTES + 60))
    events = fetch_events(today_start, fetch_end)
    state = load_state()
    sent_count = 0

    # 1) 아침 요약 (실행이 조금 늦어져도 요약 시각부터 3시간 안이면 보냄)
    today_str = now.date().isoformat()
    if SUMMARY_HOUR >= 0 and state.get("summary_date") != today_str and SUMMARY_HOUR <= now.hour < SUMMARY_HOUR + 3:
        todays = [e for e in events if e["start"].date() == now.date()]
        send_telegram(summary_text(todays, now))
        state["summary_date"] = today_str
        sent_count += 1

    # 2) 일정 N분 전 알림 (종일 일정 제외)
    #    실행 지연을 고려해, 시작 10분 지난 일정까지는 아직 안 보냈으면 보냄
    window_end = now + dt.timedelta(minutes=REMIND_MINUTES)
    late_limit = now - dt.timedelta(minutes=10)
    for e in events:
        if e["all_day"] or e["key"] in state["sent"]:
            continue
        if late_limit <= e["start"] <= window_end:
            send_telegram(reminder_text(e, now))
            state["sent"][e["key"]] = e["start"].isoformat()
            sent_count += 1

    save_state(state, now)
    print(f"확인 완료: 일정 {len(events)}개 조회, 알림 {sent_count}건 전송")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test()
    else:
        run()
