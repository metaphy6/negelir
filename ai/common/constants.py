"""
Negelir — Constants, team mappings, and domain knowledge.
Per roadmap §6.2: team names → UUIDs; no source-identifying data.
"""

MODEL_VERSION = "0.3.0"
CURRENT_SEASON = "2025-2026"
MAX_INPUT_LENGTH = 200
N_FEATURES = 130

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
    # Abbreviations & nicknames
    "gs":               "team_001",
    "cim bom":          "team_001",
    "cimbom":           "team_001",
    "aslan":            "team_001",
    "fb":               "team_002",
    "fener":            "team_002",
    "kanarya":          "team_002",
    "bjk":              "team_003",
    "kartal":           "team_003",
    "kara kartal":      "team_003",
    "ts":               "team_004",
    "bordo mavi":       "team_004",
    "fırtına":          "team_004",
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
    # Match / result
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
    # Extended (1000+ question coverage)
    "galip", "galibiyet", "mağlup", "mağlubiyet", "alır", "alabilir",
    "favori", "kazanabilir", "yenilmezlik", "gol atar", "gol atılır",
    "kale", "kaleci", "savunma", "defans", "hücum", "forvet",
    "sakatlık", "sakat", "kadroda", "oynar", "oynuyor",
    "asist", "gol krallığı", "şampiyonluk", "küme düşer", "küme düşme",
    "sıralama", "sırada", "avrupa", "kupa", "play-off",
    "ofsayt", "var", "frikik", "hat-trick", "hat trick",
    "kırmızı kart", "sarı kart", "faul", "müdahale",
    "karşılıklı", "karşılıklı gol", "kale kapanır", "clean sheet",
    "erken gol", "son dakika", "uzatma", "90+",
    "iç saha", "dış saha", "evinde", "deplasmanında",
    "düşüşte", "yükselişte", "formda", "form", "son formu",
    "gol ortalaması", "yediği gol", "attığı gol",
    "puanla", "3 puan", "kazanma", "yenme",
    "sezon", "bu sezon", "bu hafta", "hafta", "lig sıralaması",
    "kafa kafaya", "h2h", "son 5 maç", "son 10 maç",
    "skoru", "kaça kaç", "kaç kaç", "final skoru",
    "gollü", "golsüz", "az gollü", "çok gollü",
    "ikinci yarıda", "devre", "devre arası",
    "oyuncu", "yıldız", "penaltıları", "vuruyor",
    # Team abbreviations & nicknames
    "gs", "fb", "bjk", "ts", "cim bom", "cimbom", "aslan",
    "fener", "kanarya", "kartal", "kara kartal", "bordo mavi", "fırtına",
    # Conversational / colloquial
    "ne dersin", "ne düşünüyorsun", "sence", "sizce", "tahmin et",
    "bence", "analiz", "yorumun", "fikrini", "görüşün",
    "yapar", "halleder", "söker", "döver", "geçer", "ezer",
    "yenişemez", "paylaşır", "götürür",
    # Betting shorthand (pattern only, not output)
    "ms1", "ms2", "msx", "1x2", "kg", "btts",
    "handikap", "çifte şans", "ilk gol", "maç sonu",
    "bol gol", "gol çıkar", "gol var mı",
    # Time references
    "bugün", "bu akşam", "yarın", "bu hafta sonu", "bu pazar",
    "bu cumartesi",
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
