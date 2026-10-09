"""Ground explicit session counts, per-session time and day spacing from source text."""
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo
from focusos_api.planning_request import NUMBER, WORDS
from focusos_api.planning_selection import SessionSelection


def grounded_sessions(command: str, reference: str, zone: str) -> SessionSelection | None:
    text = re.sub(r'"[^"\n]*"', ' ', command.lower())
    count = re.search(r"\b(?:schedule|jadwalkan|jadwal|buat|bikin|schedule for)\s+(" + NUMBER + r")\s*(?:hari|days?|sesi|sessions?)\b", text)
    span = re.search(r"\b(?:tanggal|dates?|between|from)\s+(\d{4}-\d{2}-\d{2})\s*(?:-|to|sampai|hingga|dan|and)\s*(\d{4}-\d{2}-\d{2})\b", text)
    if not span:
        span = re.search(r"\b(?:tanggal|dates?)\s+(\d{1,2})\s*(?:-|to|sampai|hingga|dan|and)\s*(\d{1,2})(?![\d:])", text)
    duration = re.search(r"(?:tiap\s+(?:hari|sesi)(?:\s+schedule(?:nya|\s+nya)?)?|setiap\s+(?:hari|sesi)|each\s+(?:day|session))\s*(?:selama|for)?\s*(" + NUMBER + r")\s*(jam|hours?|menit|minutes?)\b", text)
    if not duration:
        duration = re.search(r"\b(" + NUMBER + r")\s*(jam|hours?|menit|minutes?)\s*(?:per\s+(?:hari|sesi|day|session)|each)\b", text)
    if not (count and span and duration): return None
    def number(value): return WORDS[value] if value in WORDS else float(value.replace(',', '.'))
    total = number(count[1]); minutes = number(duration[1]) * (60 if duration[2].startswith(('jam','hour')) else 1)
    if not float(total).is_integer() or not float(minutes).is_integer(): return None
    anchor = datetime.fromisoformat(reference).astimezone(ZoneInfo(zone)).date()
    try:
        if len(span[1]) == 10:
            first, last = date.fromisoformat(span[1]), date.fromisoformat(span[2])
        else:
            first, last = date(anchor.year, anchor.month, int(span[1])), date(anchor.year, anchor.month, int(span[2]))
        # Do not silently reinterpret a differently named month or year.
        if len(span[1]) != 10 and re.search(r"\b(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|january|february|march|may|june|july|august|october|december|bulan depan|next month)\b", text):
            return None
        spacing = 1
        gap = re.search(r"\b(?:longkap|langkap|lompat|lewati|skip)\s+(" + NUMBER + r")\s*(?:hari|days?)\b", text)
        if gap:
            omitted = number(gap[1])
            if not float(omitted).is_integer(): return None
            spacing = int(omitted) + 1
        elif re.search(r"(?:tidak|ga|gak|nggak|jangan|bukan|not|non)[^.\n]{0,40}(?:berturut|consecutive)", text):
            spacing = 2
        return SessionSelection(count=int(total), minutes=int(minutes), date_start=first.isoformat(), date_end=last.isoformat(), min_days_between=spacing)
    except ValueError:
        return None
