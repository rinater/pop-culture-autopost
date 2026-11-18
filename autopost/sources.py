import calendar
import logging
import re
import time
from dataclasses import dataclass

import feedparser
import httpx
from bs4 import BeautifulSoup

from .textutil import strip_tags

log = logging.getLogger("autopost.sources")

HEADERS = {"User-Agent": "pop-culture-autopost/1.0 (contact: you@example.com)"}
BSKY_API = "https://public.api.bsky.app/xrpc"
_BSKY_POST_RE = re.compile(r"^https://bsky\.app/profile/([^/]+)/post/([A-Za-z0-9]+)")


@dataclass
class Item:
    url: str
    title: str
    summary: str
    source: str
    published_ts: int
    image: str | None = None


def base_source(name: str) -> str:
    """'Bluesky/IGN' -> 'IGN': репост IGN в Bluesky не считается независимым источником."""
    return name.split("/")[-1]


def _get(url: str, params=None, timeout: float = 20.0) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = httpx.get(url, params=params, headers=HEADERS, timeout=timeout, follow_redirects=True)
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            last = e
            time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def _rss_image(entry) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key, []) or []:
            if m.get("url"):
                return m["url"]
    for enc in entry.get("enclosures", []) or []:
        if str(enc.get("type", "")).startswith("image") and enc.get("href"):
            return enc["href"]
    return None


def fetch_feed(name: str, url: str, max_age_sec: int) -> list[Item]:
    try:
        resp = _get(url)
    except Exception as e:
        log.warning("лента %s недоступна: %s", name, e)
        return []

    parsed = feedparser.parse(resp.content)
    now = time.time()
    items: list[Item] = []
    for e in parsed.entries[:50]:
        link = e.get("link")
        title = strip_tags(e.get("title", ""))
        if not link or not title:
            continue
        ts_struct = e.get("published_parsed") or e.get("updated_parsed")
        ts = calendar.timegm(ts_struct) if ts_struct else int(now)
        if now - ts > max_age_sec:
            continue
        items.append(Item(
            url=link,
            title=title,
            summary=strip_tags(e.get("summary", ""))[:600],
            source=name,
            published_ts=ts,
            image=_rss_image(e),
        ))
    log.info("%s: %d подходящих записей", name, len(items))
    return items


def fetch_og_image(url: str) -> str | None:
    """Запасной вариант: og:image со страницы статьи."""
    try:
        soup = BeautifulSoup(_get(url).text, "html.parser")
        tag = soup.find("meta", attrs={"property": "og:image"})
        return tag["content"] if tag and tag.get("content") else None
    except Exception:
        return None


def bsky_engagement(urls: list[str]) -> dict[str, tuple[int, int]]:
    """Возвращает {url: (likes, reposts)} через публичный API без токенов."""
    did_cache: dict[str, str] = {}
    uri_to_url: dict[str, str] = {}

    for url in urls:
        m = _BSKY_POST_RE.match(url)
        if not m:
            continue
        handle, rkey = m.groups()
        if handle.startswith("did:"):
            did = handle
        elif handle in did_cache:
            did = did_cache[handle]
        else:
            try:
                did = _get(f"{BSKY_API}/com.atproto.identity.resolveHandle",
                           params={"handle": handle}).json()["did"]
            except Exception as e:
                log.warning("не удалось resolveHandle %s: %s", handle, e)
                continue
            did_cache[handle] = did
        uri_to_url[f"at://{did}/app.bsky.feed.post/{rkey}"] = url

    result: dict[str, tuple[int, int]] = {}
    uris = list(uri_to_url)
    for i in range(0, len(uris), 25):
        chunk = uris[i:i + 25]
        try:
            posts = _get(f"{BSKY_API}/app.bsky.feed.getPosts",
                         params={"uris": chunk}).json().get("posts", [])
        except Exception as e:
            log.warning("getPosts не ответил: %s", e)
            continue
        for p in posts:
            url = uri_to_url.get(p.get("uri", ""))
            if url:
                result[url] = (p.get("likeCount", 0), p.get("repostCount", 0))
    return result
