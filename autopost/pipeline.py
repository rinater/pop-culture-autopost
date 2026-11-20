import logging
import re
import time
from dataclasses import dataclass

from .config import BSKY_FEEDS, RSS_FEEDS, SOURCE_PRIORITY, Settings
from .llm import LLMClient, LLMUnavailable
from .prompt import SYSTEM_PROMPT
from .sources import Item, base_source, bsky_engagement, fetch_feed, fetch_og_image
from .storage import Storage
from .telegram import Telegram
from .textutil import sanitize_html, similarity

log = logging.getLogger("autopost.pipeline")

SIM = 0.5
SCORE_RE = re.compile(r"SCORE:\s*(\d{1,2})", re.IGNORECASE)
NOISE_RE = re.compile(
    r"\b(\d+\s+(best|greatest|worst)|top\s+\d+|best\s+of|review|recap|guide|walkthrough|"
    r"deal|sale|birthday|рецензия|обзор|гайд|подборка|скидк[аи])\b",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    item: Item
    group: list[Item]
    resonance: bool


def _is_bsky(it: Item) -> bool:
    return it.source.startswith("Bluesky/")


def _raw_post(it: Item) -> str:
    """Режим без LLM: заголовок и краткое описание на языке источника."""
    text = f"<b>{sanitize_html(it.title)}</b>"
    if it.summary:
        text += f"\n\n{sanitize_html(it.summary[:300])}"
    return text


def _edit(llm: LLMClient, c: Candidate, recent_titles: list[str], threshold: int) -> str | None:
    sources = sorted({base_source(o.source) for o in c.group})
    parts = ["Последние заголовки канала (не повторять эти темы):"]
    parts += [f"- {t}" for t in recent_titles] or ["- (нет)"]
    parts.append(f"\nПодтверждений: {len(c.group)}; источники: {', '.join(sources)}; "
                 f"резонанс: {'да' if c.resonance else 'нет'}.")
    for o in c.group[:5]:
        parts.append(f"\n[{o.source}] {o.title}\n{o.summary}")

    raw = llm.complete(SYSTEM_PROMPT, "\n".join(parts))

    m = SCORE_RE.search(raw)
    score = int(m.group(1)) if m else 0
    if c.resonance:
        score = min(10, score + 1)
    body = SCORE_RE.sub("", raw, count=1).strip()

    if not body or body.upper().startswith("SKIP"):
        log.info("SKIP моделью (score=%d): %s", score, c.item.title[:80])
        return None
    if score < threshold:
        log.info("ниже порога (score=%d < %d): %s", score, threshold, c.item.title[:80])
        return None
    return sanitize_html(body)


def run(s: Settings) -> None:
    store = Storage(s.db_path)
    now = int(time.time())
    max_age = s.item_max_age_hours * 3600
    sent = 0
    llm_attempts = 0

    try:
        # 1. Сбор
        fetched: list[Item] = []
        for name, url in RSS_FEEDS + BSKY_FEEDS:
            fetched += fetch_feed(name, url, max_age)
        new_count = sum(store.add_item(it) for it in fetched)
        log.info("получено %d, новых %d", len(fetched), new_count)

        # 2. Предфильтр по ключевым словам (экономит LLM-квоту)
        pending = store.pending(now - max_age)
        noise_urls = {it.url for it in pending if NOISE_RE.search(it.title)}
        store.set_status(list(noise_urls), "skipped")
        pending = [it for it in pending if it.url not in noise_urls]

        # 3. Дедупликация по опубликованным темам + кросс-источниковый резонанс
        window = store.window(now - s.resonance_hours * 3600)
        posted = store.posted_titles(now - 7 * 86400)
        cands: list[Candidate] = []
        for it in pending:
            if any(similarity(it.title, t) >= SIM for t in posted):
                store.set_status([it.url], "duplicate")
                continue
            siblings = [o for o in window if o.url != it.url and similarity(it.title, o.title) >= SIM]
            group = [it] + siblings
            resonance = len({base_source(o.source) for o in group}) >= 2
            cands.append(Candidate(item=it, group=group, resonance=resonance))

        # 4. Фильтр Bluesky по вовлечённости
        eng = bsky_engagement([c.item.url for c in cands if _is_bsky(c.item)])
        final: list[Candidate] = []
        for c in cands:
            if _is_bsky(c.item):
                likes, reposts = eng.get(c.item.url, (0, 0))
                if not (likes >= s.bsky_min_likes or reposts >= s.bsky_min_reposts):
                    store.set_status([c.item.url], "low_engagement")
                    continue
            final.append(c)

        # 5. Приоритет: резонанс, затем приоритет источника, затем свежесть
        final.sort(
            key=lambda c: (
                c.resonance,
                max(SOURCE_PRIORITY.get(base_source(o.source), 1) for o in c.group),
                c.item.published_ts,
            ),
            reverse=True,
        )

        # 6. Редактура (если включена), картинка, отправка
        llm = LLMClient(s) if s.use_llm else None
        tg = Telegram(s.tg_token, s.tg_chat_id, s.dry_run)
        handled: set[str] = set()
        recent_titles = posted[:20]

        for c in final:
            if sent >= s.max_posts_per_run:
                break
            if c.item.url in handled:
                continue

            if s.use_llm:
                if llm_attempts >= s.max_llm_calls_per_run:
                    log.info("лимит LLM на запуск исчерпан")
                    break
                if store.llm_calls_today() >= s.max_llm_calls_per_day:
                    log.warning("дневной лимит LLM исчерпан")
                    break
                llm_attempts += 1
                store.bump_llm_calls()
                try:
                    body = _edit(llm, c, recent_titles, s.virality_threshold)
                except LLMUnavailable:
                    log.warning("LLM недоступна, запуск останавливается; новости остаются в очереди")
                    break
                except Exception:
                    log.exception("ошибка обработки %s", c.item.url)
                    store.set_status([c.item.url], "error")
                    continue
            else:
                body = _raw_post(c.item)

            group_urls = [o.url for o in c.group]
            handled.update(group_urls)
            if body is None:
                store.set_status([c.item.url], "skipped")
                store.set_status([u for u in group_urls if u != c.item.url], "merged")
                continue

            link = f'\n\n<a href="{c.item.url}">Источник: {base_source(c.item.source)}</a>'
            photo = c.item.image or fetch_og_image(c.item.url)

            if tg.send(body + link, photo):
                sent += 1
                store.set_status([c.item.url], "posted")
                store.set_status([u for u in group_urls if u != c.item.url], "merged")
                store.mark_posted([o.title for o in c.group])
                recent_titles = [c.item.title] + recent_titles
            else:
                store.set_status([c.item.url], "error")

        store.purge(now - 30 * 86400)
        log.info("готово: отправлено %d, LLM-вызовов %d", sent, llm_attempts)
    finally:
        store.close()
