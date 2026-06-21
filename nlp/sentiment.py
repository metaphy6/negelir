"""
Negelir — Turkish sentiment analysis.
Per roadmap §5.6.4: sandboxed, outputs only float [-1, 1], text never stored.
Rule-based for PoC; can be upgraded to distilled BERT-tiny later.
"""

import re

from common.logger import get_logger

log = get_logger("nlp.sentiment")

# ── Turkish football sentiment lexicon ──────────────────
_POSITIVE_WORDS = [
    "galibiyet", "kazandı", "zafer", "başarı", "mükemmel", "harika",
    "güçlü", "dominant", "üstün", "muhteşem", "şampiyon", "lider",
    "gol", "net", "fırsat", "atak", "ofansif", "etkili", "istikrar",
    "yükseliş", "form", "motivasyon", "moral", "birlik", "uyum",
    "savunma sağlam", "kalesini kapattı", "seri", "rekor",
]

_NEGATIVE_WORDS = [
    "mağlubiyet", "kaybetti", "yenilgi", "başarısız", "kötü", "zayıf",
    "düşüş", "gerileme", "kriz", "problem", "sorun", "eksik",
    "sakatlık", "ceza", "kırmızı kart", "ihraç", "hata", "penaltı kaçırdı",
    "gol yedi", "dağıldı", "çöktü", "moral bozuk", "istikrarsız",
    "teknik direktör değişikliği", "kovuldu", "ayrıldı", "transfer bitti",
]

# Injection detection (per roadmap §5.6.4 point 6)
_INJECTION_WORDS = [
    "ignore previous", "system prompt", "forget instructions",
    "[INST]", "<|im_start|>", "you are now", "ignore above",
]


def analyze_sentiment(text: str) -> float:
    """
    Analyze sentiment of Turkish football text.
    Returns a float between -1.0 (very negative) and 1.0 (very positive).

    Per roadmap §5.6.4:
    - Input text is processed in memory only
    - Output is a single float
    - Injection attempts return neutral 0.0
    - Text is NOT stored anywhere

    Args:
        text: Turkish text to analyze

    Returns:
        Sentiment score: float in [-1.0, 1.0]
    """
    if not text or not text.strip():
        return 0.0

    # Injection detection
    text_lower = text.lower()
    for marker in _INJECTION_WORDS:
        if marker.lower() in text_lower:
            log.warning("⛔ NLP injection attempt detected — returning neutral (0.0)")
            return 0.0

    # Count positive and negative words
    positive_count = sum(1 for word in _POSITIVE_WORDS if word in text_lower)
    negative_count = sum(1 for word in _NEGATIVE_WORDS if word in text_lower)

    total = positive_count + negative_count
    if total == 0:
        return 0.0

    # Score: normalized difference
    score = (positive_count - negative_count) / max(total, 1)

    # Clamp to [-1, 1]
    score = max(-1.0, min(1.0, score))

    log.debug(f"📝 Sentiment analysis: +{positive_count}/-{negative_count} → {score:.3f}")

    # Text goes out of scope here — never stored (per roadmap)
    return round(score, 3)


def batch_analyze(texts: list[str], max_texts: int = 50) -> list[float]:
    """
    Analyze sentiment for a batch of texts.
    Per roadmap §5.6.4 point 4: max 50 texts per match day cycle.
    """
    if len(texts) > max_texts:
        log.warning(f"⚠️  Text limit exceeded: {len(texts)} > {max_texts}, processing first {max_texts}")
        texts = texts[:max_texts]

    scores = [analyze_sentiment(t) for t in texts]
    avg = sum(scores) / len(scores) if scores else 0.0
    log.info(f"📊 Batch sentiment analysis: {len(scores)} texts, avg: {avg:.3f}")
    return scores
