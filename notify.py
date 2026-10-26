"""
네이버 캘린더 → 텔레그램
- 매일 08:48 오늘 일정 목록
- 월요일 08:48에는 이번 주(월~일) 일정 목록도 추가로
"""

import datetime as dt
import html
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import caldav
import recurring_ical_events
import requests

KST = ZoneInfo("Asia/Seoul")
SEND_AT = (8, 48)  # 보내는 시각 (시, 분)
WEEKDAYS = "월화수목금토일"


def env(name):
    value = (os.environ.get(name) or "").strip()
    if not value:
        sys.exit(f"[오류] {name} 가 비어 있습니다. GitHub Secrets를 확인하세요.")
    return value


NAVER_ID = env("NAVER_ID")
NAVER_APP_PASSWORD = env("NAVER_APP_PASSWORD")
TG_TOKEN = env("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = env("TELEGRAM_CHAT_ID")


def send_telegram(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=20,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"텔레그램 전송 실패 ({type(e).__name__})") from None
    if r.status_code != 200:
        raise RuntimeError(f"텔레그램 전송 실패 (HTTP {r.status_code}): {r.text[:200]}")


def get_calendars():
    client = caldav.DAVClient(
        url="https://caldav.calendar.naver.com", username=NAVER_ID, password=NAVER_APP_PASSWORD
    )
    return client.principal().calendars()


def fetch_events(day_start, day_end):
    events = {}
    for cal in get_calendars():
        try:
            results = cal.search(start=day_start, end=day_end, event=True)
        except Exception as e:
            print(f"[경고] 캘린더 하나를 읽지 못했습니다 ({type(e).__name__})")
            continue
        for res in results:
            try:
                for ev in recurring_ical_events.of(res.icalendar_instance).between(day_start, day_end):
                    if ev.get("DTSTART") is None:
                        continue
                    start = ev.get("DTSTART").dt
                    all_day = not isinstance(start, dt.datetime)
                    if all_day:
                        start = dt.datetime.combine(start, dt.time(0), KST)
                    elif start.tzinfo is None:
                        start = start.replace(tzinfo=KST)
                    start = start.astimezone(KST)
                    title = str(ev.get("SUMMARY", "") or "(제목 없음)")
                    key = (str(ev.get("UID", "")), start.isoformat())
                    events[key] = {
                        "title": title,
                        "location": str(ev.get("LOCATION", "") or ""),
                        "start": start,
                        "all_day": all_day,
                    }
            except Exception as e:
                print(f"[경고] 일정 하나를 해석하지 못했습니다 ({type(e).__name__})")
    # 날짜별로, 같은 날은 제목 순
    return sorted(events.values(), key=lambda e: (e["start"].date(), e["title"]))


def fmt_day(d):
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def fmt_line(e):
    line = f"• {html.escape(e['title'])}"
    if e["location"]:
        line += f"\n   📍 {html.escape(e['location'])}"
    return line


def today_message(events, today):
    if not events:
        return f"📅 {fmt_day(today)} 오늘 일정\n\n등록된 일정이 없어요."
    return f"📅 {fmt_day(today)} 오늘 일정 ({len(events)}개)\n\n" + "\n".join(fmt_line(e) for e in events)


def week_message(events, monday):
    sunday = monday + dt.timedelta(days=6)
    head = f"🗓 이번 주 일정 {fmt_day(monday)} ~ {fmt_day(sunday)}"
    if not events:
        return head + "\n\n이번 주는 등록된 일정이 없어요."
    parts = [f"{head} ({len(events)}개)"]
    for i in range(7):
        d = (monday + dt.timedelta(days=i)).date()
        day_events = [e for e in events if e["start"].date() == d]
        if day_events:
            parts.append(f"<b>[{fmt_day(d)}]</b>\n" + "\n".join(fmt_line(e) for e in day_events))
    return "\n\n".join(parts)


def main():
    now = dt.datetime.now(KST)

    # 자동 실행일 때는 08:48까지 기다렸다가 보냄 (수동 실행은 바로 보냄)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        target = now.replace(hour=SEND_AT[0], minute=SEND_AT[1], second=0, microsecond=0)
        wait = (target - now).total_seconds()
        if 0 < wait < 3600:
            print(f"{int(wait)}초 기다렸다가 보냅니다.")
            time.sleep(wait)
        now = dt.datetime.now(KST)

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    is_manual = os.environ.get("GITHUB_EVENT_NAME") != "schedule"

    # 1) 오늘 일정
    events = fetch_events(day_start, day_start + dt.timedelta(days=1))
    send_telegram(today_message(events, now))
    print(f"오늘 일정 전송: {len(events)}개")

    # 2) 월요일이면 이번 주 일정도 (수동 실행 땐 확인용으로 항상 보냄)
    if now.weekday() == 0 or is_manual:
        monday = day_start - dt.timedelta(days=now.weekday())
        week = fetch_events(monday, monday + dt.timedelta(days=7))
        send_telegram(week_message(week, monday))
        print(f"이번 주 일정 전송: {len(week)}개")

    # 저장소 활동 기록 (GitHub는 60일간 활동이 없으면 자동 실행을 멈춤)
    Path("state").mkdir(exist_ok=True)
    Path("state/last_sent.txt").write_text(now.date().isoformat() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
