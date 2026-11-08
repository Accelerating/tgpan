import re

from fastapi import Request

from app.common.locales.en import MESSAGES

_PLACEHOLDER = re.compile(r"\{(p\d+)\}")


def _message_pattern(source: str) -> re.Pattern:
    parts = _PLACEHOLDER.split(source)
    return re.compile(
        "".join(f"(?P<{part}>.+)" if i % 2 else re.escape(part) for i, part in enumerate(parts)), re.S
    )


_PATTERNS = [
    (_message_pattern(source), target) for source, target in MESSAGES.items() if _PLACEHOLDER.search(source)
]


def detect_locale(header: str) -> str:
    preferences = []
    for item in header.split(","):
        tag, *parameters = item.strip().lower().split(";")
        quality = 1.0
        for parameter in parameters:
            if parameter.strip().startswith("q="):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0
        if 0 < quality <= 1 and re.fullmatch(r"[a-z]+(?:[-_][a-z0-9]+)*", tag):
            preferences.append((quality, tag.split("-")[0].split("_")[0]))
    for _, language in sorted(preferences, key=lambda item: -item[0]):
        if language in ("zh", "en"):
            return "zh-CN" if language == "zh" else "en"
    return "en"


def translate(message: str | None, request: Request) -> str | None:
    if message is None or detect_locale(request.headers.get("accept-language", "")) == "zh-CN":
        return message
    if message in MESSAGES:
        return MESSAGES[message]
    for pattern, target in _PATTERNS:
        if match := pattern.fullmatch(message):
            # Substitute once, so names containing placeholder-like text remain untouched.
            return _PLACEHOLDER.sub(lambda token: match[token[1]], target)
    return message


def translate_fields(record: dict, request: Request, *fields: str) -> dict:
    return record | {key: translate(record[key], request) for key in fields if key in record}
