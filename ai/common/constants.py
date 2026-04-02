"""
Negelir — Constants, team mappings, and domain knowledge.
Per roadmap §6.2: team names → UUIDs; no source-identifying data.
"""

MODEL_VERSION = "0.1.0"
CURRENT_SEASON = "2025-2026"
MAX_INPUT_LENGTH = 200
N_FEATURES = 91

# ── Team UUID registry ──────────────────────────────────
# Maps display names to internal UUIDs (per roadmap §6.2)
TEAM_MAP: dict[str, str] = {
    "galatasaray":      "team_001",
    "fenerbahçe":       "team_002",
    "fenerbahce":       "team_002",
    "beşiktaş":         "team_003",
    "besiktas":         "team_003",
    "trabzonspor":      "team_004",
    "başakşehir":       "team_005",
    "basaksehir":       "team_005",
    "adana demirspor":  "team_006",
    "antalyaspor":      "team_007",
    "alanyaspor":       "team_008",
    "kasımpaşa":        "team_009",
    "kasimpasa":        "team_009",
    "konyaspor":        "team_010",
    "sivasspor":        "team_011",
    "kayserispor":      "team_012",
    "gaziantep":        "team_013",
    "gaziantep fk":     "team_013",
    "hatayspor":        "team_014",
    "samsunspor":       "team_015",
    "rizespor":         "team_016",
    "çaykur rizespor":  "team_016",
    "pendikspor":       "team_017",
    "karagümrük":       "team_018",
    "fatih karagümrük": "team_018",
    "ankaragücü":       "team_019",
    "eyüpspor":         "team_050",
    "göztepe":          "team_051",
    "bodrum fk":        "team_052",
    "sakaryaspor":      "team_053",
    "keçiörengücü":     "team_054",
}

# Reverse map: uuid → display name
UUID_TO_NAME: dict[str, str] = {
    "team_001": "Galatasaray",
    "team_002": "Fenerbahçe",
    "team_003": "Beşiktaş",
    "team_004": "Trabzonspor",
    "team_005": "Başakşehir",
    "team_006": "Adana Demirspor",
    "team_007": "Antalyaspor",
    "team_008": "Alanyaspor",
    "team_009": "Kasımpaşa",
    "team_010": "Konyaspor",
    "team_011": "Sivasspor",
    "team_012": "Kayserispor",
    "team_013": "Gaziantep FK",
    "team_014": "Hatayspor",
    "team_015": "Samsunspor",
    "team_016": "Çaykur Rizespor",
    "team_017": "Pendikspor",
    "team_018": "Fatih Karagümrük",
    "team_019": "Ankaragücü",
    "team_050": "Eyüpspor",
    "team_051": "Göztepe",
    "team_052": "Bodrum FK",
    "team_053": "Sakaryaspor",
    "team_054": "Keçiörengücü",
}

# ── Football domain keywords (Turkish) ──────────────────
# Used by TQU football domain gate (roadmap §5.1 TQU Step 2)
FOOTBALL_KEYWORDS: list[str] = [
    "maç", "maçta", "maçı", "gol", "golü", "kazanır", "kazanir",
    "yener", "biter", "bitermi", "kaybeder", "berabere", "skor",
    "takım", "takim", "üst", "ust", "alt", "forma", "lig",
    "süper", "super", "deplasman", "ev sahibi", "puan",
    "averaj", "kart", "kırmızı", "sarı", "korner", "penaltı",
    "yarı", "yari", "ilk yarı", "ikinci yarı", "sonuç",
    "galatasaray", "fenerbahçe", "fenerbahce", "beşiktaş", "besiktas",
    "trabzonspor", "başakşehir", "basaksehir", "performans",
    "nasıl", "olur mu", "atar mı", "yemez mi", "kapanır mı",
    "kg", "karşılaşma", "derbi", "şampiyon",
]

# ── Leagues ──────────────────────────────────────────────
LEAGUES = {
    "super_lig": {"name": "Trendyol Süper Lig", "tier": 1, "teams": 19},
    "lig_1":     {"name": "Trendyol 1. Lig",    "tier": 2, "teams": 18},
}

# ── Compliance: Banned words (per roadmap §3.1) ─────────
# Never appear in any user-facing output
BANNED_WORDS: list[str] = [
    "bahis", "iddaa", "kupon", "odds", "oran", "wager", "bet",
    "tip", "guaranteed", "sure", "profit", "earning", "kazanç",
    "para", "money", "casino", "gambling", "stake",
    "prediction", "winner", "tahmin",
]
