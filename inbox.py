"""
텔레그램 → 네이버 캘린더 (종일 일정 등록)

보내는 형식 (한 줄에 일정 하나, 여러 줄 가능)
  1008 치과예약 0910   → 10월 8일 종일 일정 "치과예약 0910"
  0120 부모님댁방문    → 1월 20일 (올해 이미 지났으면 내년)
  토요일 리나수업      → 이번 주(월~일) 토요일   ("토"만 써도 됨)
"""

import datetime as dt
import json
import os
import re
import sys
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

import caldav
import requests

KST = ZoneInfo("Asia/Seoul")
STATE_FILE = Path("state/telegram_offset.json")
WEEKDAYS = "월화수목금토일"


def env(name, default=None):
    value = (os.environ.get(name) or "").strip()
    if not value and default is None:
        sys.exit(f"[오류] {name} 가 비어 있습니다. GitHub Secrets를 확인하세요.")
    return value or default


NAVER_ID = env("NAVER_ID")
NAVER_APP_PASSWORD = env("NAVER_APP_PASSWORD")
TG_TOKEN = env("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = env("TELEGRAM_CHAT_ID")
TARGET_CALENDAR = env("TARGET_CALENDAR", "")  # 비우면 기본 캘린더


# ---------------------------------------------------------------- 텔레그램

def tg(method, **params):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/{method}", json=params, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"텔레그램 호출 실패 ({type(e).__name__})") from None
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"텔레그램 오류: {data.get('description')}")
    return data["result"]


def reply(text):
    tg("sendMessage", chat_id=TG_CHAT_ID, text=text)


# ---------------------------------------------------------------- 해석

def parse_line(line, today):
    """한 줄을 (날짜, 제목)으로. 형식이 틀리면 None"""
    line = line.strip()
    if not line:
        return None

    # 1) MMDD 제목
    m = re.match(r"^(\d{4})\s+(.+)$", line)
    if m:
        month, day = int(m.group(1)[:2]), int(m.group(1)[2:])
        title = m.group(2).strip()
        for year in (today.year, today.year + 1):
            try:
                date = dt.date(year, month, day)
            except ValueError:
                return None
            if date >= today:
                return date, title
        return None

    # 2) 요일 제목  (토요일 / 토)
    m = re.match(r"^([월화수목금토일])(?:요일)?\s+(.+)$", line)
    if m:
        monday = today - dt.timedelta(days=today.weekday())
        date = monday + dt.timedelta(days=WEEKDAYS.index(m.group(1)))
        return date, m.group(2).strip()

    return None


# ---------------------------------------------------------------- 네이버 캘린더

def get_target_calendar():
    client = caldav.DAVClient(
        url="https://caldav.calendar.naver.com", username=NAVER_ID, password=NAVER_APP_PASSWORD
    )
    calendars = client.principal().calendars()
    if not calendars:
        raise RuntimeError("네이버 캘린더를 찾지 못했습니다.")
    if TARGET_CALENDAR:
        for c in calendars:
            if (c.name or "") == TARGET_CALENDAR:
                return c
    for c in calendars:
        if "내 캘린더" in (c.name or ""):
            return c
    return calendars[0]


def add_all_day_event(cal, date, title):
    def esc(s):
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ics = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//naver-telegram-alarm//KO",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{date:%Y%m%d}",
        f"DTEND;VALUE=DATE:{date + dt.timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{esc(title)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ])
    cal.save_event(ics)


# ---------------------------------------------------------------- 실행

def load_offset():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("offset", 0)
    except Exception:
        return 0


def save_offset(offset):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"offset": offset}) + "\n", encoding="utf-8")


def fmt_date(d):
    year = f"{d.year}년 " if d.year != dt.datetime.now(KST).year else ""
    return f"{year}{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


HELP = (
    "이렇게 보내주세요 (한 줄에 하나)\n\n"
    "1008 치과예약 0910\n"
    "0120 부모님댁방문\n"
    "토요일 리나수업"
)


def main():
    offset = load_offset()
    updates = tg("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
    if not updates:
        print("새 메시지 없음")
        return

    today = dt.datetime.now(KST).date()
    cal = None
    for u in updates:
        offset = u["update_id"] + 1
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != TG_CHAT_ID:
            continue  # 내 채팅이 아니면 무시
        text = (msg.get("text") or "").strip()
        if not text or text.startswith("/"):
            if text in ("/start", "/help"):
                reply(HELP)
            continue

        done, failed = [], []
        for line in text.splitlines():
            if not line.strip():
                continue
            parsed = parse_line(line, today)
            if not parsed:
                failed.append(line.strip())
                continue
            date, title = parsed
            if cal is None:
                cal = get_target_calendar()
            add_all_day_event(cal, date, title)
            done.append(f"• {fmt_date(date)}  {title}")

        parts = []
        if done:
            parts.append("✅ 등록했어요\n" + "\n".join(done))
        if failed:
            parts.append("⚠️ 형식을 모르겠어요\n" + "\n".join(f"• {f}" for f in failed) + "\n\n" + HELP)
        if parts:
            reply("\n\n".join(parts))

    save_offset(offset)
    print(f"메시지 {len(updates)}개 처리")


if __name__ == "__main__":
    main()
