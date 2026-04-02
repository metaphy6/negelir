"""
Negelir TQU — Regex patterns for Turkish football intent classification.
Per roadmap §5.1: ~10 intent types, rule-based, zero neural network.
"""

import re
from dataclasses import dataclass

# ── Intent types ────────────────────────────────────────


@dataclass
class IntentPattern:
    intent_id: str
    patterns: list[re.Pattern]
    keywords: list[str]
    weight: float = 1.0


# ── Compiled patterns per intent ────────────────────────

INTENT_PATTERNS: list[IntentPattern] = [
    # match_winner — "Galatasaray kazanır mı?", "Bu maçı kim alır?"
    IntentPattern(
        intent_id="match_winner",
        patterns=[
            re.compile(r"(kazanır|kazanir|yener|alır|alir|galip)\s*(mı|mi|mu|mü)", re.I),
            re.compile(r"(kim|hangi\s*takım)\s*(kazanır|kazanir|alır|alir|yener)", re.I),
            re.compile(r"(maçı|maci)\s*(kim|hangi)\s*(alır|alir|kazanır|kazanir)", re.I),
            re.compile(r"(ev\s*sahibi|deplasman).*(kazanır|kazanir|yener)", re.I),
        ],
        keywords=["kazanır", "kazanir", "yener", "galip", "kim alır", "mağlup"],
    ),

    # draw — "Berabere biter mi?", "Bu maç beraberlik olur mu?"
    IntentPattern(
        intent_id="draw",
        patterns=[
            re.compile(r"berabere\s*(biter|kalır|olur)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"beraberlik\s*(olur|çıkar|biter)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(eşitlik|eşit)\s*(biter|olur)\s*(mi|mı|mu|mü)", re.I),
        ],
        keywords=["berabere", "beraberlik", "eşitlik"],
    ),

    # over_under — "Bu maç üst biter mi?", "Alt olur mu?"
    IntentPattern(
        intent_id="over_under",
        patterns=[
            re.compile(r"(üst|ust)\s*(biter|olur|çıkar)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(alt)\s*(biter|olur|çıkar|kalır)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(2\.5|2,5)\s*(üst|ust|alt|üstü|üzeri)", re.I),
            re.compile(r"(üstü|üzeri|altı|altında)\s*(biter|olur|çıkar)\s*(mi|mı|mu|mü)", re.I),
        ],
        keywords=["üst", "ust", "alt", "2.5", "üzeri", "altı"],
    ),

    # goal_range — "Bu maçta 4-6 gol olur mu?", "3'ten fazla gol olur mu?"
    IntentPattern(
        intent_id="goal_range",
        patterns=[
            re.compile(r"(\d+)\s*[-–]\s*(\d+)\s*gol", re.I),
            re.compile(r"(\d+)\s*'?\s*(ten|dan|den|tan)\s*(fazla|çok|az)\s*gol", re.I),
            re.compile(r"(\d+)\s*(gol|golün|goldan)\s*(fazla|üstü|üzeri|az|altı)", re.I),
            re.compile(r"(toplam|kaç)\s*gol", re.I),
        ],
        keywords=["gol", "kaç gol", "toplam gol", "fazla gol"],
    ),

    # both_teams_score — "İki takım da gol atar mı?", "KG var mı?"
    IntentPattern(
        intent_id="both_teams_score",
        patterns=[
            re.compile(r"(iki|her\s*iki)\s*(takım|takim)\s*(da|de)?\s*(gol|skor)", re.I),
            re.compile(r"(kg|karşılıklı\s*gol)\s*(var|olur|çıkar)\s*(mı|mi|mu|mü)?", re.I),
            re.compile(r"(iki\s*taraf|her\s*iki\s*taraf).*(gol|skor)", re.I),
        ],
        keywords=["kg", "karşılıklı gol", "iki takım", "her iki taraf"],
    ),

    # clean_sheet — "Gol yemez mi?", "Kale kapanır mı?"
    IntentPattern(
        intent_id="clean_sheet",
        patterns=[
            re.compile(r"(gol)\s*(yemez|yemeden|yemedi)\s*(mi|mı|mu|mü)?", re.I),
            re.compile(r"(kale)\s*(kapanır|kapanir|kapatır)\s*(mı|mi|mu|mü)", re.I),
            re.compile(r"(sıfır|0)\s*(gol|skor).*(biter|kalır)", re.I),
        ],
        keywords=["yemez", "kale kapanır", "sıfır gol", "clean sheet"],
    ),

    # half_time — "İlk yarı nasıl biter?", "İlk yarıda gol olur mu?"
    IntentPattern(
        intent_id="half_time",
        patterns=[
            re.compile(r"(ilk|birinci|1\.?)\s*(yarı|yari)\s*(nasıl|da|de|sonucu)", re.I),
            re.compile(r"(ikinci|2\.?)\s*(yarı|yari)\s*(nasıl|da|de|sonucu)", re.I),
            re.compile(r"(devre\s*arası|ilk\s*yarı).*(gol|skor|sonuç)", re.I),
        ],
        keywords=["ilk yarı", "ikinci yarı", "devre arası", "yarıda"],
    ),

    # form_query — "Takımın son formu nasıl?", "Performansları nasıl?"
    IntentPattern(
        intent_id="form_query",
        patterns=[
            re.compile(r"(son|güncel)\s*(form|performans)", re.I),
            re.compile(r"(nasıl|iyi|kötü)\s*(oynuyor|gidiyor|performans)", re.I),
            re.compile(r"(takım|takim)\s*(formu|performansı)", re.I),
        ],
        keywords=["form", "performans", "nasıl oynuyor", "gidiyor"],
    ),

    # head_to_head — "Bu iki takım son maçlarda nasıl oynadı?"
    IntentPattern(
        intent_id="head_to_head",
        patterns=[
            re.compile(r"(kafa\s*kafaya|karşılaşma|son\s*maçlar)", re.I),
            re.compile(r"(iki\s*takım|aralarında).*(maç|karşılaşma|oynadı)", re.I),
            re.compile(r"(son|önceki)\s*(karşılaşma|maçlar)", re.I),
        ],
        keywords=["kafa kafaya", "karşılaşma", "son maçlar", "aralarında"],
    ),
]

# Quick lookup
INTENT_MAP: dict[str, IntentPattern] = {p.intent_id: p for p in INTENT_PATTERNS}
