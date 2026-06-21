"""
Negelir — Bet market type definitions for backtesting.

Each BetMarket knows how to:
  1. Extract a prediction from the model ``analysis`` dict.
  2. Determine the actual outcome from real match data.
  3. Compare prediction vs actual.

Only markets whose actual outcome can be computed from available match
data (ft_home, ft_away, ht_home, ht_away) are included.  Card / corner
markets have no ground-truth data so they are prediction-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# ── Outcome helpers ──────────────────────────────────────

def _result_label(home: int, away: int) -> str:
    if home > away:
        return "1"
    if home == away:
        return "X"
    return "2"


def _ht_ft_label(ht_home: int, ht_away: int, ft_home: int, ft_away: int) -> str:
    return f"{_result_label(ht_home, ht_away)}/{_result_label(ft_home, ft_away)}"


def _winning_margin(ft_home: int, ft_away: int) -> str:
    diff = ft_home - ft_away
    if diff >= 3:
        return "Ev 3+"
    if diff == 2:
        return "Ev 2"
    if diff == 1:
        return "Ev 1"
    if diff == 0:
        return "0"
    if diff == -1:
        return "Dep 1"
    if diff == -2:
        return "Dep 2"
    return "Dep 3+"


# ── Bet market definition ───────────────────────────────

@dataclass
class BetMarketResult:
    """Single market evaluation for one match."""
    market_id: str
    market_name_tr: str
    predicted: str
    actual: str
    confidence: float
    correct: bool
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class BetMarket:
    """A single betting market that can be evaluated."""
    id: str
    name_tr: str
    name_en: str
    category: str           # e.g. "match_result", "over_under", "goals", "half_time", "score", "cards"
    requires_ht: bool = False
    prediction_only: bool = False  # True if no actual outcome data exists (cards, corners)

    def predict(self, analysis: dict) -> tuple[str, float, dict[str, float]]:
        """Extract predicted outcome, confidence, probabilities from analysis.
        Override per market.  Returns (label, confidence, probs_dict)."""
        raise NotImplementedError

    def resolve_actual(self, match: dict) -> str | None:
        """Determine actual outcome from match data.  None = cannot evaluate."""
        raise NotImplementedError

    def evaluate(self, analysis: dict, match: dict) -> BetMarketResult | None:
        predicted, confidence, probs = self.predict(analysis)
        if self.prediction_only:
            return BetMarketResult(
                market_id=self.id, market_name_tr=self.name_tr,
                predicted=predicted, actual="N/A", confidence=confidence,
                correct=False, probabilities=probs,
            )
        actual = self.resolve_actual(match)
        if actual is None:
            return None
        return BetMarketResult(
            market_id=self.id, market_name_tr=self.name_tr,
            predicted=predicted, actual=actual,
            confidence=confidence,
            correct=predicted == actual,
            probabilities=probs,
        )


# ── Concrete markets ────────────────────────────────────

class MatchResult1X2(BetMarket):
    """Maç Sonucu (1X2)."""
    def __init__(self):
        super().__init__("ms", "Maç Sonucu (1X2)", "Match Result", "match_result")

    def predict(self, a):
        d = a.get("distribution", {})
        probs = {"1": d.get("home_win", 0.33),
                 "X": d.get("draw", 0.34),
                 "2": d.get("away_win", 0.33)}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        return _result_label(m["ft_home"], m["ft_away"])


class DoubleChance(BetMarket):
    """Çifte Şans – pick the most-likely pair."""
    def __init__(self):
        super().__init__("cs", "Çifte Şans", "Double Chance", "match_result")

    def predict(self, a):
        bm = a.get("betting_markets", {})
        probs = {"1-X": bm.get("dc_1x", 0.5),
                 "1-2": bm.get("dc_12", 0.5),
                 "X-2": bm.get("dc_x2", 0.5)}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        r = _result_label(m["ft_home"], m["ft_away"])
        # DC outcomes that match
        actuals = set()
        if r in ("1", "X"):
            actuals.add("1-X")
        if r in ("1", "2"):
            actuals.add("1-2")
        if r in ("X", "2"):
            actuals.add("X-2")
        return "|".join(sorted(actuals))  # multiple can be correct

    def evaluate(self, analysis, match):
        predicted, confidence, probs = self.predict(analysis)
        actual_str = self.resolve_actual(match)
        if actual_str is None:
            return None
        correct = predicted in actual_str.split("|")
        return BetMarketResult(
            market_id=self.id, market_name_tr=self.name_tr,
            predicted=predicted, actual=actual_str,
            confidence=confidence, correct=correct, probabilities=probs,
        )


class FirstHalfResult(BetMarket):
    """İlk Yarı Sonucu."""
    def __init__(self):
        super().__init__("iy", "İlk Yarı Sonucu", "First Half Result",
                         "half_time", requires_ht=True)

    def predict(self, a):
        bm = a.get("betting_markets", {})
        probs = {"1": bm.get("ht_home", 0.33),
                 "X": bm.get("ht_draw", 0.34),
                 "2": bm.get("ht_away", 0.33)}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        ht_h = m.get("ht_home")
        ht_a = m.get("ht_away")
        if ht_h is None or ht_a is None:
            return None
        return _result_label(ht_h, ht_a)


class SecondHalfResult(BetMarket):
    """İkinci Yarı Sonucu."""
    def __init__(self):
        super().__init__("2y", "İkinci Yarı Sonucu", "Second Half Result",
                         "half_time", requires_ht=True)

    def predict(self, a):
        # Second-half probs derived: FT distribution minus HT effect
        d = a.get("distribution", {})
        bm = a.get("betting_markets", {})
        # Approximate: use FT as proxy (no separate 2H prediction in model)
        probs = {"1": d.get("home_win", 0.33),
                 "X": d.get("draw", 0.34),
                 "2": d.get("away_win", 0.33)}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        ht_h = m.get("ht_home")
        ht_a = m.get("ht_away")
        if ht_h is None or ht_a is None:
            return None
        sh_h = m["ft_home"] - ht_h
        sh_a = m["ft_away"] - ht_a
        return _result_label(sh_h, sh_a)


class HalfTimeFullTime(BetMarket):
    """İlk Yarı / Maç Sonucu."""
    def __init__(self):
        super().__init__("iy_ms", "İlk Yarı / Maç Sonucu", "HT/FT",
                         "half_time", requires_ht=True)

    def predict(self, a):
        bm = a.get("betting_markets", {})
        d = a.get("distribution", {})
        ht_probs = {"1": bm.get("ht_home", 0.33),
                    "X": bm.get("ht_draw", 0.34),
                    "2": bm.get("ht_away", 0.33)}
        ft_probs = {"1": d.get("home_win", 0.33),
                    "X": d.get("draw", 0.34),
                    "2": d.get("away_win", 0.33)}
        combos = {}
        for ht_label, ht_p in ht_probs.items():
            for ft_label, ft_p in ft_probs.items():
                combos[f"{ht_label}/{ft_label}"] = ht_p * ft_p
        total = sum(combos.values()) or 1.0
        combos = {k: v / total for k, v in combos.items()}
        best = max(combos, key=combos.get)
        return best, combos[best], combos

    def resolve_actual(self, m):
        ht_h = m.get("ht_home")
        ht_a = m.get("ht_away")
        if ht_h is None or ht_a is None:
            return None
        return _ht_ft_label(ht_h, ht_a, m["ft_home"], m["ft_away"])


class WinningMargin(BetMarket):
    """Kazanma Marjı."""
    def __init__(self):
        super().__init__("km", "Kazanma Marjı", "Winning Margin", "match_result")

    def predict(self, a):
        sp = a.get("score_prediction", [])
        if not sp:
            return "0", 0.1, {}
        # Tally margin probs from score matrix
        margin_probs: dict[str, float] = {}
        for s in sp:
            h, aw, p = s["home"], s["away"], s["probability"]
            label = _winning_margin(h, aw)
            margin_probs[label] = margin_probs.get(label, 0.0) + p
        if not margin_probs:
            return "0", 0.1, {}
        best = max(margin_probs, key=margin_probs.get)
        return best, margin_probs[best], margin_probs

    def resolve_actual(self, m):
        return _winning_margin(m["ft_home"], m["ft_away"])


class OverUnder(BetMarket):
    """Alt/Üst for a specific goal line."""
    def __init__(self, line: float):
        label_tr = f"Alt/Üst {line}"
        label_en = f"Over/Under {line}"
        super().__init__(f"au_{line}", label_tr, label_en, "over_under")
        self.line = line

    def predict(self, a):
        bm = a.get("betting_markets", {})
        gm = a.get("goal_metrics", {})
        key = f"over_{str(self.line).replace('.', '_')}"
        over_prob = bm.get(key, gm.get(f"over_{str(self.line).replace('.', '_')}_prob", 0.5))
        under_prob = 1.0 - over_prob
        probs = {"Üst": over_prob, "Alt": under_prob}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        total = m["ft_home"] + m["ft_away"]
        return "Üst" if total > self.line else "Alt"


class FirstHalfOverUnder05(BetMarket):
    """İlk Yarı Alt/Üst 0.5."""
    def __init__(self):
        super().__init__("iy_au_05", "İY Alt/Üst 0.5", "FH Over/Under 0.5",
                         "half_time", requires_ht=True)

    def predict(self, a):
        bm = a.get("betting_markets", {})
        over = bm.get("ht_over_0_5", 0.7)
        probs = {"Üst": over, "Alt": 1.0 - over}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        ht_h = m.get("ht_home")
        ht_a = m.get("ht_away")
        if ht_h is None or ht_a is None:
            return None
        return "Üst" if (ht_h + ht_a) > 0.5 else "Alt"


class BothTeamsScore(BetMarket):
    """Karşılıklı Gol (KG Var/Yok)."""
    def __init__(self):
        super().__init__("kg", "Karşılıklı Gol", "Both Teams Score", "goals")

    def predict(self, a):
        bm = a.get("betting_markets", {})
        gm = a.get("goal_metrics", {})
        btts = bm.get("btts", gm.get("bts_prob", 0.5))
        probs = {"Var": btts, "Yok": 1.0 - btts}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        return "Var" if m["ft_home"] > 0 and m["ft_away"] > 0 else "Yok"


class OddEvenGoals(BetMarket):
    """Toplam Gol Tek/Çift."""
    def __init__(self):
        super().__init__("tc", "Toplam Gol Tek/Çift", "Odd/Even Goals", "goals")

    def predict(self, a):
        sb = a.get("score_brackets", {})
        sp = a.get("score_prediction", [])
        # Sum probabilities for odd/even totals from score predictions
        odd_p, even_p = 0.0, 0.0
        for s in sp:
            total = s["home"] + s["away"]
            if total % 2 == 0:
                even_p += s["probability"]
            else:
                odd_p += s["probability"]
        if odd_p + even_p < 0.01:
            odd_p, even_p = 0.5, 0.5
        else:
            total_p = odd_p + even_p
            odd_p /= total_p
            even_p /= total_p
        probs = {"Tek": odd_p, "Çift": even_p}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        total = m["ft_home"] + m["ft_away"]
        return "Tek" if total % 2 == 1 else "Çift"


class CorrectScore(BetMarket):
    """Skor Tahmini — top-1 predicted scoreline."""
    def __init__(self):
        super().__init__("skor", "Skor Tahmini", "Correct Score", "score")

    def predict(self, a):
        sp = a.get("score_prediction", [])
        if not sp:
            return "1-1", 0.1, {}
        top = sp[0]
        label = f"{top['home']}-{top['away']}"
        probs = {f"{s['home']}-{s['away']}": s["probability"] for s in sp}
        return label, top["probability"], probs

    def resolve_actual(self, m):
        return f"{m['ft_home']}-{m['ft_away']}"


class CorrectScoreTop3(BetMarket):
    """Skor Tahmini (İlk 3) — correct if actual is in top-3 predictions."""
    def __init__(self):
        super().__init__("skor_top3", "Skor Tahmini (İlk 3)", "Correct Score Top 3", "score")

    def predict(self, a):
        sp = a.get("score_prediction", [])
        if not sp:
            return "1-1", 0.1, {}
        top = sp[0]
        label = f"{top['home']}-{top['away']}"
        probs = {f"{s['home']}-{s['away']}": s["probability"] for s in sp[:3]}
        return label, top["probability"], probs

    def resolve_actual(self, m):
        return f"{m['ft_home']}-{m['ft_away']}"

    def evaluate(self, analysis, match):
        sp = analysis.get("score_prediction", [])
        top3_labels = {f"{s['home']}-{s['away']}" for s in sp[:3]}
        actual = self.resolve_actual(match)
        predicted, confidence, probs = self.predict(analysis)
        correct = actual in top3_labels
        return BetMarketResult(
            market_id=self.id, market_name_tr=self.name_tr,
            predicted=f"{predicted} (ilk 3: {', '.join(sorted(top3_labels))})",
            actual=actual, confidence=confidence,
            correct=correct, probabilities=probs,
        )


class CorrectScoreTop5(BetMarket):
    """Skor Tahmini (İlk 5) — correct if actual is in top-5 predictions."""
    def __init__(self):
        super().__init__("skor_top5", "Skor Tahmini (İlk 5)", "Correct Score Top 5", "score")

    def predict(self, a):
        sp = a.get("score_prediction", [])
        if not sp:
            return "1-1", 0.1, {}
        top = sp[0]
        label = f"{top['home']}-{top['away']}"
        probs = {f"{s['home']}-{s['away']}": s["probability"] for s in sp[:5]}
        return label, top["probability"], probs

    def resolve_actual(self, m):
        return f"{m['ft_home']}-{m['ft_away']}"

    def evaluate(self, analysis, match):
        sp = analysis.get("score_prediction", [])
        top5_labels = {f"{s['home']}-{s['away']}" for s in sp[:5]}
        actual = self.resolve_actual(match)
        predicted, confidence, probs = self.predict(analysis)
        correct = actual in top5_labels
        return BetMarketResult(
            market_id=self.id, market_name_tr=self.name_tr,
            predicted=f"{predicted} (ilk 5: {', '.join(sorted(top5_labels))})",
            actual=actual, confidence=confidence,
            correct=correct, probabilities=probs,
        )


class CleanSheetHome(BetMarket):
    """Ev Sahibi Gol Yemez."""
    def __init__(self):
        super().__init__("cs_home", "Ev Sahibi Gol Yemez", "Home Clean Sheet", "goals")

    def predict(self, a):
        bm = a.get("betting_markets", {})
        btts = bm.get("btts", 0.5)
        # P(away scores 0) ≈ 1 - btts (rough estimate)
        d = a.get("distribution", {})
        home_xg = a.get("goal_metrics", {}).get("away_xg", 1.0)
        import math
        cs_prob = math.exp(-home_xg)  # Poisson P(0)
        probs = {"Evet": cs_prob, "Hayır": 1.0 - cs_prob}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        return "Evet" if m["ft_away"] == 0 else "Hayır"


class CleanSheetAway(BetMarket):
    """Deplasman Gol Yemez."""
    def __init__(self):
        super().__init__("cs_away", "Deplasman Gol Yemez", "Away Clean Sheet", "goals")

    def predict(self, a):
        home_xg = a.get("goal_metrics", {}).get("home_xg", 1.3)
        import math
        cs_prob = math.exp(-home_xg)
        probs = {"Evet": cs_prob, "Hayır": 1.0 - cs_prob}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        return "Evet" if m["ft_home"] == 0 else "Hayır"


class TotalGoalsBracket(BetMarket):
    """Toplam Gol Aralığı (0, 1, 2, 3, 4+)."""
    def __init__(self):
        super().__init__("tg_bracket", "Toplam Gol Aralığı", "Total Goals Bracket", "goals")

    def predict(self, a):
        sb = a.get("score_brackets", {})
        probs = {
            "0 gol": sb.get("goals_0", 0.05),
            "1 gol": sb.get("goals_1", 0.10),
            "2 gol": sb.get("goals_2", 0.25),
            "3 gol": sb.get("goals_3", 0.25),
            "4+ gol": sb.get("goals_4_plus", 0.20),
        }
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        total = m["ft_home"] + m["ft_away"]
        if total == 0:
            return "0 gol"
        if total == 1:
            return "1 gol"
        if total == 2:
            return "2 gol"
        if total == 3:
            return "3 gol"
        return "4+ gol"


class CardsPrediction(BetMarket):
    """Tahmini Sarı Kart Sayısı (sadece tahmin, doğrulama yok)."""
    def __init__(self):
        super().__init__("cards", "Tahmini Kart Sayısı", "Expected Cards",
                         "cards", prediction_only=True)

    def predict(self, a):
        cp = a.get("card_prediction", {})
        ey = cp.get("expected_yellows", 4.0)
        over35 = cp.get("over_3_5_cards", 0.5)
        probs = {
            f"~{ey:.0f} sarı kart": 1.0,
            "3.5 Üst": over35,
            "3.5 Alt": 1.0 - over35,
        }
        label = f"~{ey:.0f} sarı kart"
        if over35 > 0.5:
            label += " (3.5Ü)"
        else:
            label += " (3.5A)"
        return label, max(over35, 1.0 - over35), probs

    def resolve_actual(self, m):
        return "N/A"


class RedCardProbability(BetMarket):
    """Kırmızı Kart Olasılığı (sadece tahmin)."""
    def __init__(self):
        super().__init__("red_card", "Kırmızı Kart Olasılığı", "Red Card Probability",
                         "cards", prediction_only=True)

    def predict(self, a):
        cp = a.get("card_prediction", {})
        rp = cp.get("red_card_probability", 0.08)
        probs = {"Var": rp, "Yok": 1.0 - rp}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def resolve_actual(self, m):
        return "N/A"


# ── Market registry ──────────────────────────────────────

ALL_MARKETS: list[BetMarket] = [
    MatchResult1X2(),
    DoubleChance(),
    FirstHalfResult(),
    SecondHalfResult(),
    HalfTimeFullTime(),
    WinningMargin(),
    OverUnder(1.5),
    OverUnder(2.5),
    OverUnder(3.5),
    FirstHalfOverUnder05(),
    BothTeamsScore(),
    OddEvenGoals(),
    CorrectScore(),
    CorrectScoreTop3(),
    CorrectScoreTop5(),
    CleanSheetHome(),
    CleanSheetAway(),
    TotalGoalsBracket(),
    CardsPrediction(),
    RedCardProbability(),
]

EVALUABLE_MARKETS = [m for m in ALL_MARKETS if not m.prediction_only]
PREDICTION_ONLY_MARKETS = [m for m in ALL_MARKETS if m.prediction_only]

MARKET_BY_ID: dict[str, BetMarket] = {m.id: m for m in ALL_MARKETS}

# Categories for report grouping
CATEGORIES = {
    "match_result": "TARAF BAHİSLERİ",
    "half_time": "YARI SONUCU BAHİSLERİ",
    "over_under": "ALT/ÜST BAHİSLERİ",
    "goals": "GOL BAHİSLERİ",
    "score": "SKOR TAHMİNİ",
    "cards": "KART TAHMİNLERİ (sadece tahmin)",
}

# Turkish question templates per market (for the report)
MARKET_QUESTIONS_TR: dict[str, list[str]] = {
    "ms": [
        "Bu maçın sonucu ne olur?",
        "Maçı kim kazanır?",
        "1X2 tahmini nedir?",
    ],
    "cs": [
        "Çifte şans tahmini nedir?",
        "En güvenli çifte şans bahsi hangisi?",
    ],
    "iy": [
        "İlk yarı sonucu ne olur?",
        "Devre arası skor ne olur?",
    ],
    "2y": [
        "İkinci yarı sonucu ne olur?",
        "İkinci yarıda kim kazanır?",
    ],
    "iy_ms": [
        "İlk yarı / maç sonucu ne olur?",
        "İY/MS tahmini nedir?",
    ],
    "km": [
        "Hangi takım kaç farkla kazanır?",
        "Kazanma marjı ne olur?",
    ],
    "au_1.5": [
        "Bu maçta 1.5 üstü gol olur mu?",
        "1.5 alt/üst tahmini nedir?",
    ],
    "au_2.5": [
        "Bu maçta 2.5 üstü gol olur mu?",
        "Maçta üst biter mi?",
    ],
    "au_3.5": [
        "Bu maçta 3.5 üstü gol olur mu?",
        "Gol festivali olur mu?",
    ],
    "iy_au_05": [
        "İlk yarıda gol olur mu?",
        "İlk yarı golsüz geçer mi?",
    ],
    "kg": [
        "Karşılıklı gol olur mu?",
        "İki takım da gol atar mı?",
    ],
    "tc": [
        "Toplam gol tek mi çift mi?",
        "Tek/çift tahmini nedir?",
    ],
    "skor": [
        "Bu maçın skoru ne olur?",
        "Skor tahmininiz nedir?",
    ],
    "skor_top3": [
        "En olası 3 skor nedir?",
        "Skor ihtimalleri nelerdir?",
    ],
    "skor_top5": [
        "En olası 5 skor nedir?",
    ],
    "cs_home": [
        "Ev sahibi kalesini korur mu?",
        "Ev sahibi gol yemez mi?",
    ],
    "cs_away": [
        "Deplasman takımı kalesini korur mu?",
        "Deplasman gol yemez mi?",
    ],
    "tg_bracket": [
        "Bu maçta kaç gol olur?",
        "Toplam gol aralığı nedir?",
    ],
    "cards": [
        "Bu maçta kaç sarı kart olur?",
        "Kart 3.5 üstü olur mu?",
    ],
    "red_card": [
        "Bu maçta kırmızı kart olur mu?",
    ],
}
