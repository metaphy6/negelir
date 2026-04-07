"""
Negelir — Configuration loaded from environment variables.
All settings respect Docker Compose injection.
"""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # PostgreSQL
    pg_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    pg_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    pg_db: str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "negelir"))
    pg_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "negelir"))
    pg_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "negelir_dev_2026"))

    # Redis
    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))

    # Go server
    server_url: str = field(default_factory=lambda: os.getenv("SERVER_URL", "http://localhost:8080"))

    # AI
    device: str = field(default_factory=lambda: os.getenv("AI_DEVICE", "auto"))
    log_level: str = field(default_factory=lambda: os.getenv("AI_LOG_LEVEL", "DEBUG"))

    # Scraping
    scrape_rate_limit: int = field(default_factory=lambda: int(os.getenv("SCRAPE_RATE_LIMIT_SECONDS", "5")))
    scrape_user_agent: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_USER_AGENT", "Negelir/0.1 (Football Analysis Research)"
    ))
    scrape_respect_robots: bool = field(default_factory=lambda: os.getenv(
        "SCRAPE_RESPECT_ROBOTS_TXT", "true"
    ).lower() in ("true", "1", "yes"))

    # Scraping data sources
    scrape_source_a: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_A", "https://arsiv.mackolik.com"
    ))
    scrape_source_b: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_B", "https://www.mackolik.com"
    ))
    scrape_source_c: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_C", "https://www.tff.org"
    ))
    scrape_source_d: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_D", "https://www.mackolik.com"
    ))
    scrape_source_extra: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_EXTRA", ""
    ))

    @property
    def scrape_sources(self) -> list[dict[str, str]]:
        """All active scraping sources as a list of {name, url} dicts."""
        sources = []
        if self.scrape_source_a:
            sources.append({"name": "source_a", "label": "Statistics Archive", "url": self.scrape_source_a})
        if self.scrape_source_b:
            sources.append({"name": "source_b", "label": "Live Scores", "url": self.scrape_source_b})
        if self.scrape_source_c:
            sources.append({"name": "source_c", "label": "Official Results", "url": self.scrape_source_c})
        if self.scrape_source_d:
            sources.append({"name": "source_d", "label": "Modern Frontend", "url": self.scrape_source_d})
        for extra in self.scrape_source_extra.split(","):
            extra = extra.strip()
            if extra:
                sources.append({"name": "source_extra", "label": "Extra Source", "url": extra})
        return sources

    # Paths
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "/data"))
    model_dir: str = field(default_factory=lambda: os.getenv("MODEL_DIR", "/data/models"))

    @property
    def pg_dsn(self) -> str:
        return f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} user={self.pg_user} password={self.pg_password}"

    @property
    def pg_url(self) -> str:
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_db}"


# Singleton
cfg = Config()
