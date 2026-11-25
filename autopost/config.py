import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


RSS_FEEDS: list[tuple[str, str]] = [
    ("Dexerto", "https://www.dexerto.com/feed/"),
    ("Variety", "https://variety.com/feed/"),
    ("Deadline", "https://deadline.com/feed/"),
    ("THR", "https://www.hollywoodreporter.com/feed/"),
    ("IGN", "https://feeds.feedburner.com/ign/all"),
    ("Polygon", "https://www.polygon.com/rss/index.xml"),
    ("Pitchfork", "https://pitchfork.com/feed/feed-news/rss"),
    ("Collider", "https://collider.com/feed/"),
    ("DTF", "https://dtf.ru/rss/all"),
]

# Неофициальные RSS-ленты Bluesky: если не отвечают, пропускаются без падения.
BSKY_FEEDS: list[tuple[str, str]] = [
    ("Bluesky/IGN", "https://bsky.app/profile/ign.com/rss"),
]

# Приоритет источников для сортировки кандидатов (тай-брейк).
SOURCE_PRIORITY = {
    "Variety": 5, "Deadline": 5, "THR": 4, "Dexerto": 5,
    "IGN": 3, "Polygon": 3, "Pitchfork": 3,
}


@dataclass(frozen=True)
class Settings:
    ai_provider: str
    openrouter_key: str
    openrouter_model: str
    groq_key: str
    groq_model: str
    ollama_url: str
    ollama_model: str
    tg_token: str
    tg_chat_id: str
    virality_threshold: int
    resonance_hours: int
    bsky_min_likes: int
    bsky_min_reposts: int
    max_posts_per_run: int
    max_llm_calls_per_run: int
    max_llm_calls_per_day: int
    item_max_age_hours: int
    db_path: str
    dry_run: bool
    use_llm: bool


def _flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in ("1", "true", "yes")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def load_settings() -> Settings:
    s = Settings(
        ai_provider=os.getenv("AI_PROVIDER", "openrouter").strip().lower(),
        openrouter_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "baidu/ernie-5.5-flash-preview:free"),
        groq_key=os.getenv("GROQ_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        tg_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        tg_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        virality_threshold=_int("VIRALITY_THRESHOLD", 7),
        resonance_hours=_int("RESONANCE_HOURS", 2),
        bsky_min_likes=_int("BSKY_MIN_LIKES", 20),
        bsky_min_reposts=_int("BSKY_MIN_REPOSTS", 5),
        max_posts_per_run=_int("MAX_POSTS_PER_RUN", 2),
        max_llm_calls_per_run=_int("MAX_LLM_CALLS_PER_RUN", 10),
        max_llm_calls_per_day=_int("MAX_LLM_CALLS_PER_DAY", 200),
        item_max_age_hours=_int("ITEM_MAX_AGE_HOURS", 24),
        use_llm=_flag("USE_LLM"),
        db_path=os.getenv("DB_PATH", "data/state.db"),
        dry_run=_flag("DRY_RUN"),
    )

    if s.ai_provider == "openrouter" and not s.openrouter_key:
        raise SystemExit("Нужен OPENROUTER_API_KEY")
    if s.ai_provider == "groq" and not s.groq_key:
        raise SystemExit("Нужен GROQ_API_KEY")
    if not s.dry_run and (not s.tg_token or not s.tg_chat_id):
        raise SystemExit("Нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (или запустите с --dry-run)")

    # Dry-run использует отдельную БД, чтобы не помечать реальные посты как отправленные.
    if s.dry_run:
        root, ext = os.path.splitext(s.db_path)
        s = Settings(**{**s.__dict__, "db_path": f"{root}_dry{ext}"})
    return s
