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

    # Scraping data sources (in priority order)
    scrape_source_1: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_1", "https://www.mackolik.com"
    ))
    scrape_source_2: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_2", "https://www.nesine.com"
    ))
    scrape_source_3: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_3", "https://www.tff.org"
    ))
    scrape_source_4: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_4", "https://raw.githubusercontent.com/openfootball/football.json/master"
    ))
    scrape_source_5: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_5", "https://www.football-data.co.uk/mmz4281"
    ))
    # Fallback: historical archive (slower, throttled)
    scrape_source_fallback: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_FALLBACK", "https://arsiv.mackolik.com"
    ))
    scrape_source_extra: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_EXTRA", ""
    ))

    # Mackolik archive season IDs (read from individual env vars)
    _mackolik_season_2025_2026: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2025_2026", "70381"
    ))
    _mackolik_season_2024_2025: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2024_2025", "67287"
    ))
    _mackolik_season_2023_2024: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2023_2024", "62682"
    ))
    _mackolik_season_2022_2023: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2022_2023", "59539"
    ))
    _mackolik_season_2021_2022: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2021_2022", "55775"
    ))

    # openfootball season dirs (comma-separated "dir:label" pairs)
    _openfootball_seasons_raw: str = field(default_factory=lambda: os.getenv(
        "OPENFOOTBALL_SEASONS",
        "2018-19:2018-19,2019-20:2019-20,2020-21:2020-21,2024-25:2024-25,2025-26:2025-26",
    ))

    # football-data.co.uk season codes (comma-separated "code:label" pairs)
    _footballdata_uk_seasons_raw: str = field(default_factory=lambda: os.getenv(
        "FOOTBALLDATA_UK_SEASONS",
        "2526:2025-26,2425:2024-25,2324:2023-24,2223:2022-23,2122:2021-22,2021:2020-21,1920:2019-20,1819:2018-19",
    ))

    @property
    def scrape_mackolik_archive(self) -> str:
        """Base URL for the Mackolik historical archive (fallback source)."""
        return self.scrape_source_fallback

    @property
    def scrape_openfootball_base(self) -> str:
        """Base URL for openfootball GitHub JSON files (source 4)."""
        return self.scrape_source_4

    @property
    def scrape_footballdata_base(self) -> str:
        """Base URL for football-data.co.uk CSV archive (source 5)."""
        return self.scrape_source_5

    @property
    def mackolik_known_seasons(self) -> dict[str, int]:
        """Trendyol Süper Lig season label → Mackolik season ID."""
        return {
            "2025/2026": int(self._mackolik_season_2025_2026),
            "2024/2025": int(self._mackolik_season_2024_2025),
            "2023/2024": int(self._mackolik_season_2023_2024),
            "2022/2023": int(self._mackolik_season_2022_2023),
            "2021/2022": int(self._mackolik_season_2021_2022),
        }

    @property
    def openfootball_seasons(self) -> list[tuple[str, str]]:
        """List of (season_dir, label) pairs for openfootball Turkish Süper Lig."""
        result = []
        for entry in self._openfootball_seasons_raw.split(","):
            entry = entry.strip()
            if ":" in entry:
                dir_, label = entry.split(":", 1)
                result.append((dir_.strip(), label.strip()))
        return result

    @property
    def footballdata_uk_seasons(self) -> dict[str, str]:
        """Dict of season_code → label for football-data.co.uk."""
        result = {}
        for entry in self._footballdata_uk_seasons_raw.split(","):
            entry = entry.strip()
            if ":" in entry:
                code, label = entry.split(":", 1)
                result[code.strip()] = label.strip()
        return result

    @property
    def scrape_sources(self) -> list[dict[str, str]]:
        """All active scraping sources as a list of {name, url} dicts (priority order)."""
        _LABELS = {
            "source_1": "Live Scores & Odds",
            "source_2": "Betting Aggregator",
            "source_3": "Official Turkish FA",
            "source_4": "OpenFootball JSON",
            "source_5": "Football-Data.co.uk CSV",
            "source_fallback": "Historical Archive (Fallback)",
        }
        defined = [
            ("source_1", self.scrape_source_1),
            ("source_2", self.scrape_source_2),
            ("source_3", self.scrape_source_3),
            ("source_4", self.scrape_source_4),
            ("source_5", self.scrape_source_5),
            ("source_fallback", self.scrape_source_fallback),
        ]
        sources = [
            {"name": name, "label": _LABELS[name], "url": url}
            for name, url in defined
            if url
        ]
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
