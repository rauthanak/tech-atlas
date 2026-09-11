"""Environment settings, read from .env with os.getenv. Connections, secrets,
and default provider/model only — everything else is code or data in MongoDB
(same rule as radar-service)."""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()  # reads .env from the project root into the process environment


class Settings:
    def __init__(self) -> None:
        self.mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.mongo_db = os.getenv("MONGO_DB", "tech_atlas")

        self.model_provider = os.getenv("MODEL_PROVIDER", "openai")
        self.model_name = os.getenv("MODEL_NAME", "gpt-5.6-luna")

        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

        self.scrape_max_depth = int(os.getenv("SCRAPE_MAX_DEPTH", "8"))
        self.max_pages_per_source = int(os.getenv("MAX_PAGES_PER_SOURCE", "40"))
        self.sources_per_scout = int(os.getenv("SOURCES_PER_SCOUT", "5"))
        self.scout_concurrency = int(os.getenv("SCOUT_CONCURRENCY", "5"))
        self.scrape_delay_seconds = float(os.getenv("SCRAPE_DELAY_SECONDS", "1"))
        self.include_paid_sources = os.getenv("INCLUDE_PAID_SOURCES", "false").strip().lower() in ("1", "true", "yes")
        self.keep_full_text_runs = int(os.getenv("KEEP_FULL_TEXT_RUNS", "10"))
        self.use_playwright = os.getenv("USE_PLAYWRIGHT", "true").strip().lower() in ("1", "true", "yes")
        self.show_more_clicks = int(os.getenv("SHOW_MORE_CLICKS", "3"))

        # technology resolver (Phase B)
        self.min_docs_per_tech = int(os.getenv("MIN_DOCS_PER_TECH", "1"))
        self.resolve_batch_size = int(os.getenv("RESOLVE_BATCH_SIZE", "4000"))
        self.resolve_known_limit = int(os.getenv("RESOLVE_KNOWN_LIMIT", "1500"))

        # analyzer (Phase C)
        self.scoring_concurrency = int(os.getenv("SCORING_CONCURRENCY", "6"))

    def selected_api_key(self) -> str:
        return self.anthropic_api_key if self.model_provider == "anthropic" else self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
