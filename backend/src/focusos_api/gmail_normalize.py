"""Pure Gmail MIME normalization; no attachment downloads or remote HTML fetches."""
import base64
import binascii
import hashlib
import html
from html.parser import HTMLParser
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from focusos_api.sources import MAX_BODY_BYTES

MAX_DECODED_PART = 524288
_QUOTE_START = re.compile(r"^(?:On .{1,160} wrote:|-----Original Message-----)$", re.I)


class GmailNormalizationError(Exception):
    pass


@dataclass(frozen=True)
class NormalizedGmail:
    provider_message_id: str
    thread_id: str
    history_id: str | None
    title: str
    sender: str
    received_at: datetime
    normalized_body: str | None
    body_hash: str | None
    body_truncated: bool
    has_attachments: bool
    label_ids: tuple[str, ...]


class _SafeText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "iframe", "svg"):
            self.suppressed += 1
        elif not self.suppressed and tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "iframe", "svg") and self.suppressed:
            self.suppressed -= 1
        elif not self.suppressed and tag in ("p", "div", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)


def _header(payload: dict, name: str) -> str:
    headers = payload.get("headers")
    if isinstance(headers, list):
        for item in headers:
            if isinstance(item, dict) and str(item.get("name", "")).lower() == name.lower():
                value = item.get("value")
                return value[:500] if isinstance(value, str) else ""
    return ""


def _decode_part(part: dict) -> str | None:
    body = part.get("body")
    encoded = body.get("data") if isinstance(body, dict) else None
    if not isinstance(encoded, str):
        return None
    if len(encoded) > MAX_DECODED_PART * 2:
        raise GmailNormalizationError("MIME part too large")
    try:
        raw = base64.b64decode(encoded.replace("-", "+").replace("_", "/") + "=" * (-len(encoded) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GmailNormalizationError("Invalid MIME body encoding") from exc
    if len(raw) > MAX_DECODED_PART:
        raise GmailNormalizationError("MIME part too large")
    content_type = _header(part, "Content-Type")
    match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_.-]{1,60})", content_type, re.I)
    charset = match.group(1) if match else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _walk(part: Any, plain: list[str], rich: list[str], attachments: list[bool], depth: int = 0) -> None:
    if not isinstance(part, dict) or depth > 8:
        raise GmailNormalizationError("Invalid MIME nesting")
    mime = str(part.get("mimeType", "")).lower()
    body = part.get("body")
    if part.get("filename") or isinstance(body, dict) and body.get("attachmentId"):
        attachments[0] = True
        return
    if mime == "text/plain":
        decoded = _decode_part(part)
        if decoded is not None:
            plain.append(decoded)
    elif mime == "text/html":
        decoded = _decode_part(part)
        if decoded is not None:
            parser = _SafeText()
            parser.feed(decoded)
            rich.append("".join(parser.parts))
    parts = part.get("parts", [])
    if not isinstance(parts, list) or len(parts) > 30:
        raise GmailNormalizationError("Invalid MIME parts")
    for child in parts:
        _walk(child, plain, rich, attachments, depth + 1)


def _clean_text(value: str) -> str:
    lines = []
    for line in html.unescape(value).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", line).rstrip()
        if _QUOTE_START.match(line.strip()) or line.lstrip().startswith(">"):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _cap_utf8(value: str) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_BODY_BYTES:
        return value, False
    return encoded[:MAX_BODY_BYTES].decode("utf-8", errors="ignore").rstrip(), True


def normalize_gmail_message(message: dict) -> NormalizedGmail:
    message_id = message.get("id")
    thread_id = message.get("threadId")
    payload = message.get("payload")
    labels = message.get("labelIds")
    if not isinstance(message_id, str) or not isinstance(thread_id, str) or not isinstance(payload, dict) or not isinstance(labels, list):
        raise GmailNormalizationError("Invalid Gmail message")
    try:
        received = datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise GmailNormalizationError("Invalid Gmail timestamp") from exc
    plain: list[str] = []
    rich: list[str] = []
    attachments = [False]
    _walk(payload, plain, rich, attachments)
    chosen = "\n".join(plain) if plain else "\n".join(rich)
    normalized = _clean_text(chosen)
    capped, truncated = _cap_utf8(normalized)
    body = capped or None
    subject = _clean_text(_header(payload, "Subject")).replace("\n", " ")[:200] or "(no subject)"
    sender = _clean_text(_header(payload, "From")).replace("\n", " ")[:300]
    return NormalizedGmail(
        provider_message_id=message_id, thread_id=thread_id,
        history_id=str(message.get("historyId")) if message.get("historyId") is not None else None,
        title=subject, sender=sender, received_at=received,
        normalized_body=body, body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest() if body else None,
        body_truncated=truncated, has_attachments=attachments[0],
        label_ids=tuple(str(label) for label in labels if isinstance(label, str)),
    )
