"""
Negelir — Multi-Market Backtester
===================================
Replays the last N weeks of real match data, evaluates AI predictions
across **all** Turkish betting markets (1X2, Alt/Üst, KG, İY, Skor,
Kart, vb.) and produces a comprehensive human-readable Turkish report.

Usage (CLI):
    python -m backtest.evaluator --weeks 3
    python -m backtest.evaluator --weeks 2 --min-confidence 0.55
    python -m backtest.evaluator --weeks 5 --markets ms,au_2.5,kg

Usage (programmatic):
    from backtest.evaluator import BacktestEvaluator
    report = BacktestEvaluator().run(weeks=3)
    print(report)
"""

from __future__ import annotations

import argparse
import textwrap
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from backtest.bet_types import (
    ALL_MARKETS,
    EVALUABLE_MARKETS,
    PREDICTION_ONLY_MARKETS,
    CATEGORIES,
    MARKET_BY_ID,
    MARKET_QUESTIONS_TR,
    BetMarket,
    BetMarketResult,
)
from common.config import cfg
from common.logger import get_logger
from model.real_features import (
    EloTracker,
    H2HTracker,
    StandingsTracker,
    TeamStats,
    _build_feature_vector,
    _is_derby,
    _parse_date,
    load_real_matches,
)
from model.features import FEATURE_COLUMNS

log = get_logger("backtest")


def _bar(value: float, width: int = 20) -> str:
    filled = round(value * width)
    return "█" * filled + "░" * (width - filled)


class MarketStats:
    """Aggregate stats for a single betting market across all evaluated matches."""
    def __init__(self, market: BetMarket):
        self.market = market
        self.results: list[BetMarketResult] = []

    def add(self, r: BetMarketResult):
        self.results.append(r)

    @property
    def total(self):
        return len(self.results)

    @property
    def correct(self):
        return sum(1 for r in self.results if r.correct)

    @property
    def accuracy(self):
        return self.correct / max(self.total, 1)

    def high_conf_accuracy(self, threshold: float = 0.55):
        hc = [r for r in self.results if r.confidence >= threshold]
        if not hc:
            return 0, 0, 0.0
        c = sum(1 for r in hc if r.correct)
        return c, len(hc), c / len(hc)


class BacktestResult:
    """Stores per-match, per-market evaluation data."""

    def __init__(self):
        self.match_records: list[dict] = []
        self.market_stats: dict[str, MarketStats] = {}
        self.prediction_only_samples: list[dict] = []

    def register_market(self, market: BetMarket):
        if market.id not in self.market_stats:
            self.market_stats[market.id] = MarketStats(market)

    def add_market_result(self, r: BetMarketResult):
        if r.market_id in self.market_stats:
            self.market_stats[r.market_id].add(r)

    def add_match(self, match_info: dict):
        self.match_records.append(match_info)

    def add_prediction_only(self, sample: dict):
        self.prediction_only_samples.append(sample)

    @property
    def total_matches(self):
        return len(self.match_records)

    @property
    def overall_accuracy(self):
        total_c, total_n = 0, 0
        for ms in self.market_stats.values():
            if not ms.market.prediction_only:
                total_c += ms.correct
                total_n += ms.total
        return total_c / max(total_n, 1)

    def accuracy_by_category(self) -> dict[str, tuple[int, int, float]]:
        cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for ms in self.market_stats.values():
            if ms.market.prediction_only:
                continue
            cat[ms.market.category][0] += ms.correct
            cat[ms.market.category][1] += ms.total
        return {
            k: (v[0], v[1], v[0] / max(v[1], 1))
            for k, v in cat.items()
        }

    def calibration_buckets(self, n_buckets: int = 5) -> list[dict]:
        all_results = []
        for ms in self.market_stats.values():
            if not ms.market.prediction_only:
                all_results.extend(ms.results)
        if not all_results:
            return []
        edges = np.linspace(0.0, 1.0, n_buckets + 1)
        buckets = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            subset = [r for r in all_results if lo <= r.confidence < hi]
            if not subset:
                continue
            acc = sum(1 for r in subset if r.correct) / len(subset)
            avg_c = sum(r.confidence for r in subset) / len(subset)
            buckets.append({"range": f"{lo:.2f}-{hi:.2f}", "count": len(subset),
                            "avg_conf": avg_c, "accuracy": acc})
        return buckets


class BacktestEvaluator:
    """
    Replays historical matches to evaluate model prediction accuracy
    across all supported Turkish betting markets.
    """

    def __init__(self):
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from model.inference import GBDTInference
            self._model = GBDTInference()

    def run(
        self,
        weeks: int = 3,
        min_confidence: float = 0.0,
        market_ids: list[str] | None = None,
    ) -> str:
        """
        Run multi-market backtesting and return a human-readable report.

        Args:
            weeks: How many weeks back to evaluate.
            min_confidence: Skip predictions below this threshold.
            market_ids: Optional list of market IDs to test (default: all).
        """
        log.info(f"🔁 Multi-market backtest: last {weeks} weeks, min_confidence={min_confidence:.2f}")

        # Select markets
        if market_ids:
            markets = [MARKET_BY_ID[mid] for mid in market_ids if mid in MARKET_BY_ID]
        else:
            markets = ALL_MARKETS

        # ── Load all matches ─────────────────────────────
        all_matches = load_real_matches()
        if not all_matches:
            return "❌ No real match data available for backtesting."

        all_matches.sort(key=lambda m: _parse_date(m["date"]))
        all_matches = [
            m for m in all_matches
            if m.get("ft_home") is not None and m.get("ft_away") is not None
        ]
        if not all_matches:
            return "❌ No completed matches with scores found."

        # ── Evaluation window ────────────────────────────
        most_recent = _parse_date(all_matches[-1]["date"])
        cutoff = most_recent - timedelta(weeks=weeks)

        history = [m for m in all_matches if _parse_date(m["date"]) < cutoff]
        eval_set = [m for m in all_matches if _parse_date(m["date"]) >= cutoff]

        if not eval_set:
            return (
                f"❌ No matches found in the last {weeks} weeks "
                f"(most recent: {most_recent.date()})."
            )

        log.info(
            f"📅 Window: {_parse_date(eval_set[0]['date']).date()} → "
            f"{most_recent.date()} ({len(eval_set)} matches)"
        )
        log.info(f"📚 History: {len(history)} matches for rolling state")

        self._ensure_model()

        # ── Build rolling state from history ─────────────
        elo = EloTracker()
        team_stats: dict[str, TeamStats] = defaultdict(TeamStats)
        h2h = H2HTracker()
        standings_tracker = StandingsTracker()
        total_processed = len(history)

        def _update_trackers(match):
            home, away = match["home"], match["away"]
            fh, fa = match["ft_home"], match["ft_away"]
            elo.update(home, away, fh, fa)
            h2h.add(home, away, fh, fa)
            standings_tracker.update(home, away, fh, fa)
            h_pts = 3 if fh > fa else (1 if fh == fa else 0)
            a_pts = 3 if fa > fh else (1 if fh == fa else 0)
            team_stats[home].add({
                "date": match["date"], "gf": fh, "ga": fa,
                "ht_gf": match.get("ht_home"), "ht_ga": match.get("ht_away"),
                "pts": h_pts, "is_home": True,
                "yellows": match.get("home_yellows"),
                "fouls": match.get("home_fouls"),
            })
            team_stats[away].add({
                "date": match["date"], "gf": fa, "ga": fh,
                "ht_gf": match.get("ht_away"), "ht_ga": match.get("ht_home"),
                "pts": a_pts, "is_home": False,
                "yellows": match.get("away_yellows"),
                "fouls": match.get("away_fouls"),
            })

        for m in history:
            _update_trackers(m)

        # ── Prepare result container ─────────────────────
        result = BacktestResult()
        for mk in markets:
            result.register_market(mk)

        skipped = 0

        # ── Replay evaluation matches ────────────────────
        for idx, match in enumerate(eval_set):
            home, away = match["home"], match["away"]
            fh, fa = match["ft_home"], match["ft_away"]

            h_hist = team_stats[home]
            a_hist = team_stats[away]

            if len(h_hist.results) < 3 or len(a_hist.results) < 3:
                skipped += 1
                _update_trackers(match)
                total_processed += 1
                continue

            try:
                feature_vec = _build_feature_vector(
                    home, away, _parse_date(match["date"]), match,
                    elo, h_hist, a_hist, h2h, standings_tracker,
                    total_processed,
                    total_processed + len(eval_set) - idx,
                )
            except Exception as exc:
                log.warning(f"Feature failed {home} vs {away}: {exc}")
                skipped += 1
                _update_trackers(match)
                total_processed += 1
                continue

            fv = np.array(feature_vec, dtype=np.float32).reshape(1, -1)

            try:
                analysis = self._model.predict(fv)
            except Exception as exc:
                log.warning(f"Prediction failed {home} vs {away}: {exc}")
                skipped += 1
                _update_trackers(match)
                total_processed += 1
                continue

            # ── Evaluate each market ─────────────────────
            match_market_results: list[BetMarketResult] = []

            for mk in markets:
                if mk.requires_ht and (match.get("ht_home") is None or match.get("ht_away") is None):
                    continue

                mr = mk.evaluate(analysis, match)
                if mr is None:
                    continue

                if mk.prediction_only:
                    result.add_prediction_only({
                        "date": match["date"], "home": home, "away": away,
                        "market": mk.name_tr, "predicted": mr.predicted,
                        "confidence": mr.confidence,
                    })
                else:
                    if mr.confidence < min_confidence:
                        continue
                    result.add_market_result(mr)
                    match_market_results.append(mr)

            evaluable_results = [r for r in match_market_results if r.actual != "N/A"]
            if evaluable_results:
                match_correct = sum(1 for r in evaluable_results if r.correct)
                result.add_match(dict(
                    date=match["date"], home=home, away=away,
                    ft=f"{fh}-{fa}",
                    ht=f"{match.get('ht_home', '?')}-{match.get('ht_away', '?')}",
                    markets_evaluated=len(evaluable_results),
                    markets_correct=match_correct,
                    accuracy=match_correct / len(evaluable_results),
                    details=evaluable_results,
                ))

            _update_trackers(match)
            total_processed += 1

        return self._render_report(result, weeks, min_confidence, skipped, eval_set, markets)

    # ── Report renderer ──────────────────────────────────

    def _render_report(
        self,
        result: BacktestResult,
        weeks: int,
        min_confidence: float,
        skipped: int,
        eval_set: list[dict],
        markets: list[BetMarket],
    ) -> str:
        lines: list[str] = []
        sep = "═" * 70
        thin = "─" * 70

        lines += [
            "",
            sep,
            " NEGELIR — KAPSAMLI BAHİS TAHMİN RAPORU".center(70),
            f" Son {weeks} Hafta • {result.total_matches} Maç • "
            f"{len([m for m in markets if not m.prediction_only])} Bahis Türü".center(70),
            sep,
            "",
        ]

        if result.total_matches == 0:
            lines.append(
                "⚠️  Değerlendirilecek maç bulunamadı. "
                "min_confidence veya tarih aralığı kontrol edin."
            )
            return "\n".join(lines)

        # ═══  1. OVERALL SUMMARY  ═══
        lines += [
            "1. GENEL ÖZET",
            thin,
            f"  Değerlendirilen maç       : {result.total_matches}",
            f"  Atlanan maç               : {skipped}",
            f"  Değ. pazar (toplam tahmin) : {sum(ms.total for ms in result.market_stats.values() if not ms.market.prediction_only)}",
            f"  Genel doğruluk            : {result.overall_accuracy * 100:.1f}%  "
            f"{_bar(result.overall_accuracy)}",
        ]
        if min_confidence > 0:
            lines.append(f"  Min. güven eşiği          : {min_confidence:.0%}")
        lines.append("")

        # ═══  2. PER-CATEGORY  ═══
        lines += ["2. KATEGORİYE GÖRE DOĞRULUK", thin]
        cat_acc = result.accuracy_by_category()
        for cat_id, cat_label in CATEGORIES.items():
            if cat_id not in cat_acc:
                continue
            c, n, a = cat_acc[cat_id]
            lines.append(f"  {cat_label:<35} {c:>4}/{n:<4}  {a * 100:5.1f}%  {_bar(a, 12)}")
        lines.append("")

        # ═══  3. PER-MARKET  ═══
        lines += ["3. BAHİS TÜRÜNE GÖRE DETAYLI DOĞRULUK", thin]
        lines.append(
            f"  {'Bahis Türü':<30}  {'Doğru':<8}  {'Toplam':<8}  "
            f"{'Oran':>6}  {'Güvenli (%55+)':>16}"
        )
        lines.append("  " + "─" * 80)
        for mk in markets:
            if mk.prediction_only:
                continue
            ms = result.market_stats.get(mk.id)
            if not ms or ms.total == 0:
                continue
            hc_c, hc_n, hc_a = ms.high_conf_accuracy(0.55)
            hc_str = f"{hc_c}/{hc_n} ({hc_a * 100:.0f}%)" if hc_n > 0 else "—"
            lines.append(
                f"  {mk.name_tr:<30}  {ms.correct:>5}  /{ms.total:<5}  "
                f"{ms.accuracy * 100:5.1f}%  {hc_str:>16}"
            )
        lines.append("")

        # ═══  4. QUESTIONS & AI ANSWERS  ═══
        lines += ["4. SORULAN SORULAR VE AI YANITLARI (özet)", thin]
        for mk in markets:
            ms = result.market_stats.get(mk.id)
            if not ms:
                continue
            questions = MARKET_QUESTIONS_TR.get(mk.id, [])
            if not questions:
                continue

            lines.append(f"\n  ┌─ {mk.name_tr} ({mk.name_en})")
            for q in questions:
                lines.append(f"  │  ❓ \"{q}\"")

            samples = ms.results[:3] if ms.results else []
            if samples:
                lines.append(f"  │  Örnek tahminler:")
                for s in samples:
                    tick = "✅" if s.correct else "❌"
                    lines.append(
                        f"  │    {tick} Tahmin: {s.predicted}  |  "
                        f"Gerçek: {s.actual}  |  Güven: {s.confidence:.0%}"
                    )
            if not mk.prediction_only and ms.total > 0:
                lines.append(
                    f"  │  📊 Toplam: {ms.correct}/{ms.total} doğru ({ms.accuracy * 100:.1f}%)"
                )
            lines.append(f"  └{'─' * 60}")
        lines.append("")

        # ═══  5. PREDICTION-ONLY  ═══
        if result.prediction_only_samples:
            lines += ["5. SADECE TAHMİN (doğrulama verisi yok)", thin]
            lines.append("  Kart tahminleri — gerçek veri olmadığı için doğruluk hesaplanamaz.")
            lines.append(
                f"  {'Tarih':<12}  {'Ev Sahibi':<18}  {'Deplasman':<18}  "
                f"{'Pazar':<25}  {'Tahmin'}"
            )
            lines.append("  " + "─" * 95)
            for s in result.prediction_only_samples[:15]:
                lines.append(
                    f"  {s['date']:<12}  {s['home']:<18}  {s['away']:<18}  "
                    f"{s['market']:<25}  {s['predicted']}"
                )
            if len(result.prediction_only_samples) > 15:
                lines.append(f"  ... ve {len(result.prediction_only_samples) - 15} diğer tahmin")
            lines.append("")

        # ═══  6. CALIBRATION  ═══
        lines += ["6. GÜVENİLİRLİK KALİBRASYONU (tüm pazarlar)", thin]
        for bucket in result.calibration_buckets():
            indicator = "✅" if bucket["accuracy"] >= bucket["avg_conf"] - 0.10 else "⚠️ "
            lines.append(
                f"  Güven {bucket['range']}  →  {bucket['count']:>4} tahmin  "
                f"Doğruluk: {bucket['accuracy'] * 100:.1f}%  {indicator}"
            )
        lines.append("")

        # ═══  7. MATCH-BY-MATCH  ═══
        lines += ["7. MAÇ BAZINDA DETAY", thin]
        lines.append(
            f"  {'Tarih':<12}  {'Ev Sahibi':<18}  {'Deplasman':<18}  "
            f"{'Skor':<6}  {'İY':<6}  {'Pazar':<5}  {'Doğru':<6}  {'Oran':>5}"
        )
        lines.append("  " + "─" * 90)
        for mr in result.match_records[:50]:
            lines.append(
                f"  {mr['date']:<12}  {mr['home']:<18}  {mr['away']:<18}  "
                f"{mr['ft']:<6}  {mr['ht']:<6}  {mr['markets_evaluated']:>3}    "
                f"{mr['markets_correct']:>3}    {mr['accuracy'] * 100:5.1f}%"
            )
        if len(result.match_records) > 50:
            lines.append(f"  ... ve {len(result.match_records) - 50} diğer maç")
        lines.append("")

        # ═══  8. BEST & WORST  ═══
        evaluable_stats = [
            ms for ms in result.market_stats.values()
            if not ms.market.prediction_only and ms.total > 0
        ]
        if evaluable_stats:
            ranked = sorted(evaluable_stats, key=lambda ms: ms.accuracy, reverse=True)
            lines += ["8. EN İYİ VE EN KÖTÜ PAZARLAR", thin]
            lines.append("  🏆 En iyi:")
            for ms in ranked[:5]:
                lines.append(
                    f"     {ms.market.name_tr:<30}  {ms.accuracy * 100:5.1f}%  "
                    f"({ms.correct}/{ms.total})"
                )
            lines.append("  ⚠️  En zor:")
            for ms in ranked[-3:]:
                lines.append(
                    f"     {ms.market.name_tr:<30}  {ms.accuracy * 100:5.1f}%  "
                    f"({ms.correct}/{ms.total})"
                )
            lines.append("")

        # ═══  9. VERDICT  ═══
        lines.append(sep)
        acc = result.overall_accuracy
        if acc >= 0.55:
            verdict = "🟢 Model çoklu pazarlarda genel olarak iyi performans gösteriyor."
        elif acc >= 0.45:
            verdict = "🟡 Model ortalama; bazı pazarlarda güçlü, bazılarında zayıf."
        else:
            verdict = "🔴 Model bu dönemde yetersiz; yeniden eğitim veya veri zenginleştirme önerilir."
        lines.append(f" {verdict}")

        best_market = max(evaluable_stats, key=lambda ms: ms.accuracy) if evaluable_stats else None
        if best_market:
            lines.append(
                f" En güvenilir pazar: {best_market.market.name_tr} (%{best_market.accuracy * 100:.0f})"
            )
        lines += [sep, ""]

        return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Negelir multi-market backtester — evaluate AI across all Turkish betting markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python -m backtest.evaluator --weeks 3
              python -m backtest.evaluator --weeks 2 --min-confidence 0.55
              python -m backtest.evaluator --weeks 5 --markets ms,au_2.5,kg,iy,skor
              python -m backtest.evaluator --weeks 10 --markets all

            Available markets:
              ms        Maç Sonucu (1X2)
              cs        Çifte Şans
              iy        İlk Yarı Sonucu
              2y        İkinci Yarı Sonucu
              iy_ms     İlk Yarı / Maç Sonucu
              km        Kazanma Marjı
              au_1.5    Alt/Üst 1.5
              au_2.5    Alt/Üst 2.5
              au_3.5    Alt/Üst 3.5
              iy_au_05  İY Alt/Üst 0.5
              kg        Karşılıklı Gol
              tc        Toplam Gol Tek/Çift
              skor      Skor Tahmini (ilk 1)
              skor_top3 Skor Tahmini (ilk 3)
              skor_top5 Skor Tahmini (ilk 5)
              cs_home   Ev Sahibi Gol Yemez
              cs_away   Deplasman Gol Yemez
              tg_bracket Toplam Gol Aralığı
              cards     Kart Tahmini (doğrulama yok)
              red_card  Kırmızı Kart (doğrulama yok)
        """),
    )
    parser.add_argument("--weeks", type=int, default=3,
                        help="How many weeks back to evaluate (default: 3)")
    parser.add_argument("--min-confidence", type=float, default=0.0,
                        help="Skip predictions below this confidence (default: 0.0)")
    parser.add_argument("--markets", type=str, default=None,
                        help="Comma-separated market IDs to test (default: all)")
    args = parser.parse_args()

    market_ids = None
    if args.markets and args.markets != "all":
        market_ids = [m.strip() for m in args.markets.split(",")]

    evaluator = BacktestEvaluator()
    report = evaluator.run(
        weeks=args.weeks,
        min_confidence=args.min_confidence,
        market_ids=market_ids,
    )
    print(report)


if __name__ == "__main__":
    main()
