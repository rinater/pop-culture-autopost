import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-zа-яё0-9]{4,}", re.IGNORECASE)
_ALLOWED_RE = re.compile(r"(</?b>|</?i>)")


def strip_tags(text: str) -> str:
    """Убирает HTML из RSS-полей."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(text or ""))).strip()


def sanitize_html(text: str) -> str:
    """Оставляет только <b> и <i>, остальное экранирует для Telegram HTML."""
    parts = _ALLOWED_RE.split(text)
    return "".join(p if i % 2 else html.escape(p, quote=False) for i, p in enumerate(parts))


def _tokens(title: str) -> set[str]:
    return set(_WORD_RE.findall(title.lower()))


def similarity(a: str, b: str) -> float:
    """Коэффициент Жаккара по словам длиной от 4 символов. Простая эвристика."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
