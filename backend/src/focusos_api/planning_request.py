"""Ground simple explicit constraints in the actual command, independently of the model."""
import re

WORDS = {"one": 1, "two": 2, "three": 3, "half": 0.5,
         "satu": 1, "dua": 2, "tiga": 3, "setengah": 0.5}
NUMBER = r"(?:[0-9]+(?:[.,][0-9]+)?|one|two|three|half|satu|dua|tiga|setengah)"
UNITS = r"(?:minutes?|mins?|menit|hours?|hrs?|jam)"


def explicit_constraints(command: str) -> dict:
    # A quoted task title may itself contain dates or durations.
    text = re.sub(r'"[^"\n]*"', ' ', command.lower())
    result = {}
    if re.search(r"[0-9]+\s*(?:-|to|hingga|sampai)\s*[0-9]+\s*" + UNITS, text):
        result["question"] = "Specify one work duration instead of a range of durations."
        return result
    durations = set()
    for match in re.finditer(r"\b(" + NUMBER + r")\s*(" + UNITS + r")\b", text):
        number, unit = match.groups()
        value = WORDS[number] if number in WORDS else float(number.replace(',', '.'))
        durations.add(value * (60 if unit.startswith(('hour', 'hr')) or unit == 'jam' else 1))
    if len(durations) > 1:
        result["question"] = "Specify one total work duration for this plan."
        return result
    if durations:
        value = durations.pop()
        result["duration_minutes"] = int(value) if float(value).is_integer() else value
    if re.search(r"\b(?:before|by|sebelum|not|except|bukan|jangan)\s+(?:tomorrow|besok|today|hari ini)\b", text):
        result["question"] = "Specify the scheduling day directly, and save any exact deadline on the task."
        return result
    days = set()
    day_text = text.replace("day after tomorrow", " ")
    if re.search(r"\b(?:tomorrow|besok)\b", day_text):
        days.add('tomorrow')
    if re.search(r"\b(?:today|hari ini)\b", day_text):
        days.add('today')
    dates = set(re.findall(r"\b(?:on|pada|tanggal)\s+([0-9]{4}-[0-9]{2}-[0-9]{2})\b", text))
    if len(days) + len(dates) > 1:
        result["question"] = "Specify one scheduling day for this plan."
        return result
    if days:
        result.update(day=days.pop(), date=None)
    elif dates:
        result.update(day='date', date=dates.pop())
    return result
