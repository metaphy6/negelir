"""
Negelir — Database Seed Script
================================
Imports match data from the local JSON cache (data/tr_super_lig_real.json)
into the PostgreSQL raw_matches table for local development inspection.

Usage:
    python data/seed_db.py

Environment variables are read from .env (or Docker Compose env injection).
"""

from __future__ import annotations

import json
import os
import sys

try:
    import psycopg2
    from psycopg2.extras import execute_batch
except ImportError:
    print("❌  psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "negelir")
PG_USER = os.getenv("POSTGRES_USER", "negelir")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "negelir_dev_2026")

CACHE_PATHS = [
    "/data/tr_super_lig_real.json",
    "data/tr_super_lig_real.json",
]

LEAGUE_ID = "tr_super_lig"


def _find_cache() -> str | None:
    for path in CACHE_PATHS:
        if os.path.isfile(path):
            return path
    return None


def _infer_match_week(matches: list[dict]) -> dict[str, int]:
    """Assign match weeks by grouping matches with the same date."""
    dates = sorted({m["date"] for m in matches})
    date_to_week = {d: i + 1 for i, d in enumerate(dates)}
    return date_to_week


def main():
    cache_path = _find_cache()
    if not cache_path:
        print("❌  No cache file found. Run 'make ai-pipeline' or 'make ai-demo' first.")
        sys.exit(1)

    print(f"📂  Loading cache: {cache_path}")
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    matches = data.get("matches", [])
    if not matches:
        print("⚠️  Cache file has no matches. Run the AI pipeline first to populate it.")
        sys.exit(0)

    print(f"📊  Found {len(matches)} matches in cache")

    # Connect
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DB,
            user=PG_USER, password=PG_PASS,
            connect_timeout=5,
        )
    except Exception as exc:
        print(f"❌  Cannot connect to PostgreSQL: {exc}")
        print(f"     host={PG_HOST}:{PG_PORT} db={PG_DB} user={PG_USER}")
        print("    Make sure 'make infra' has been run first.")
        sys.exit(1)

    date_to_week = _infer_match_week(matches)

    rows = []
    for m in matches:
        score = m.get("score", {})
        ft = score.get("ft", [None, None]) if isinstance(score, dict) else [None, None]
        ht = score.get("ht", [None, None]) if isinstance(score, dict) else [None, None]

        # Support both nested score dict and flat fields
        home_score = ft[0] if ft else m.get("ft_home")
        away_score = ft[1] if ft else m.get("ft_away")
        ht_home = (ht[0] if ht else m.get("ht_home")) or None
        ht_away = (ht[1] if ht else m.get("ht_away")) or None

        stats = m.get("stats", {}) or {}
        stats_json = json.dumps(stats) if stats else None

        match_date = m.get("date") or None
        week = date_to_week.get(match_date, 0)

        rows.append((
            m.get("source", "cache"),
            LEAGUE_ID,
            m.get("season", "unknown"),
            week,
            m.get("team1") or m.get("home", ""),
            m.get("team2") or m.get("away", ""),
            home_score,
            away_score,
            ht_home,
            ht_away,
            match_date,
            stats_json,
        ))

    insert_sql = """
        INSERT INTO raw_matches
            (source_id, league_id, season, match_week, home_team, away_team,
             home_score, away_score, ht_home_score, ht_away_score, match_date, stats_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (league_id, season, match_week, home_team, away_team) DO UPDATE
            SET home_score     = EXCLUDED.home_score,
                away_score     = EXCLUDED.away_score,
                ht_home_score  = EXCLUDED.ht_home_score,
                ht_away_score  = EXCLUDED.ht_away_score,
                stats_json     = EXCLUDED.stats_json,
                scraped_at     = NOW()
    """

    try:
        with conn:
            with conn.cursor() as cur:
                execute_batch(cur, insert_sql, rows, page_size=100)
        print(f"✅  Inserted / updated {len(rows)} matches into raw_matches")
    except Exception as exc:
        print(f"❌  Insert failed: {exc}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
