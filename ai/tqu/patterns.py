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
            re.compile(r"(kazanabilir|yenebilir)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"galip\s*(gel|çık|ol)\w*\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(favori)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(mağlup|kaybeder|yenilir)\s*(olur|mi|mı|mu|mü)", re.I),
            re.compile(r"(3\s*puan|üç\s*puan)\s*(la|ile|yla)?\s*(çıkar|alır)", re.I),
            re.compile(r"(galibiyet|yenilmezlik)\s*(seri|devam|alır|sürd)", re.I),
            re.compile(r"(şansı|avantajlı)\s*(var|mı|mi|mu|mü)", re.I),
            # Colloquial / slang
            re.compile(r"(alır\s*bence|kazanır\s*bence|yener\s*bence)", re.I),
            re.compile(r"(ne\s*dersin|ne\s*düşünüyorsun).*(kazanır|yener|alır|galip)", re.I),
            re.compile(r"(sence|sizce).*(kazanır|yener|galip|alır)", re.I),
            re.compile(r"(yapar\s*mı|götürür\s*mü|halleder\s*mi)\b", re.I),
            re.compile(r"(açar\s*mı|söker\s*mi|ezer\s*mi|döver\s*mi|geçer\s*mi)", re.I),
            re.compile(r"(rahat\s*(alır|kazanır|yener))", re.I),
            re.compile(r"(ms|maç\s*sonucu)\s*(ne|kaç|1|2|x)", re.I),
            re.compile(r"\b(1x2|ms1|ms2|msx)\b", re.I),
        ],
        keywords=["kazanır", "yener", "galip", "kim alır"],
    ),

    # draw — "Berabere biter mi?", "Bu maç beraberlik olur mu?"
    IntentPattern(
        intent_id="draw",
        patterns=[
            re.compile(r"berabere\s*(biter|kalır|olur|kalabilir)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"beraberlik\s*(olur|çıkar|biter|ihtimali|olasılığı)\s*(mi|mı|mu|mü)?", re.I),
            re.compile(r"(eşitlik|eşit)\s*(biter|olur)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(golsüz|0\s*-\s*0)\s*(biter|kalır)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(1\s*-\s*1)\s*(berabere|biter)", re.I),
            re.compile(r"(skor\s*eşitliği|eşitlikle\s*ayrılır)", re.I),
            re.compile(r"berabere\s*(bitme|kaldı|kal)", re.I),
            re.compile(r"maç.*beraberlikle\s*(sonuçlanır|biter)", re.I),
            # Colloquial / slang
            re.compile(r"(bence\s*berabere|berabere\s*bence)", re.I),
            re.compile(r"(paylaş|puanları\s*paylaş)\w*\s*(mı|mi|mu|mü)", re.I),
            re.compile(r"(yenişemez|yenisemez)\s*(ler|mi|mı)?", re.I),
            re.compile(r"(x\s*çıkar|x\s*olur|sonuç\s*x)", re.I),
        ],
        keywords=["berabere", "beraberlik", "eşitlik"],
    ),

    # over_under — "Bu maç üst biter mi?", "Alt olur mu?"
    IntentPattern(
        intent_id="over_under",
        patterns=[
            re.compile(r"(üst|ust)\s*(biter|olur|çıkar)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(alt)\s*(biter|olur|çıkar|kalır)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(\d+\.?\d*)\s*(üst|ust|alt|üstü|üzeri)", re.I),
            re.compile(r"(üstü|üzeri|altı|altında)\s*(biter|olur|çıkar)\s*(mi|mı|mu|mü)", re.I),
            re.compile(r"(gollü|az\s*gollü|çok\s*gollü)\s*(biter|maç)\s*(mi|mı|mu|mü)?", re.I),
            re.compile(r"(düşük\s*skor|yüksek\s*skor|az\s*gol)\w*\s*(mı|mi|mu|mü|olur|biter)?", re.I),
            re.compile(r"(gol\s*festivali|gol\s*yağmuru)\s*(olur)?\s*(mu|mı|mi|mü)?", re.I),
            re.compile(r"(alt\s*mı|üst\s*mü|alt\s*mı\s*üst\s*mü)", re.I),
            re.compile(r"(o/u|over|under)\s*\d", re.I),
            # Colloquial / betting shorthand
            re.compile(r"(gol\s*çık|gol\s*var\s*mı|gol\s*gel)\w*\s*(mı|mi|mu|mü)?", re.I),
            re.compile(r"(skor\s*yüksek|skor\s*düşük)\s*(olur)?\s*(mu|mı)?", re.I),
            re.compile(r"(golsüz\s*kalmaz|illa\s*gol\s*olur)", re.I),
            re.compile(r"(bol\s*gol|bol\s*gollü)", re.I),
            re.compile(r"(\d+)\s*(gole|golün)\s*(üstü|altı|üzeri)", re.I),
        ],
        keywords=["üst", "ust", "alt", "2.5", "üzeri", "altı", "gollü"],
    ),

    # goal_range — "Bu maçta 4-6 gol olur mu?", "3'ten fazla gol olur mu?"
    IntentPattern(
        intent_id="goal_range",
        patterns=[
            re.compile(r"(\d+)\s*[-–]\s*(\d+)\s*gol", re.I),
            re.compile(r"(\d+)\s*'?\s*(ten|dan|den|tan)\s*(fazla|çok|az)\s*gol", re.I),
            re.compile(r"(\d+)\s*(gol|golün|goldan)\s*(fazla|üstü|üzeri|az|altı)", re.I),
            re.compile(r"(toplam|kaç)\s*gol", re.I),
            re.compile(r"(skor\s*tahmin|gol\s*beklentisi|gol\s*sayısı)", re.I),
            re.compile(r"(en\s*az|en\s*fazla)\s*(kaç)?\s*(gol|kart|korner)", re.I),
            re.compile(r"(kaça?\s*kaç|final\s*skor)\s*(biter)?", re.I),
            re.compile(r"(korner|kart).*(kaç|sayısı|\d+)", re.I),
            re.compile(r"gol.*(atılır|gelir|olur)\s*(mı|mi|mu|mü)", re.I),
            re.compile(r"(gol\s*sayısı|gol\s*ortalaması).*(kaç|nasıl)", re.I),
            re.compile(r"skoru?\s*(ne|kaç)\s*(olur|biter)", re.I),
            re.compile(r"(\d+)\s*(\+|veya\s*daha\s*fazla)\s*gol", re.I),
            re.compile(r"gol.*(geç|bul|aş)\w*\s*(mı|mi|mu|mü)", re.I),
            re.compile(r"(\d+)\s*gol\s*(ihtimal|olasılık)", re.I),
            re.compile(r"(penaltı|frikik|ofsayt|var|hat.?trick)\s*(olur|çıkar|atılır)", re.I),
            re.compile(r"(erken|son\s*dakika|90\+?)\s*(gol)", re.I),
            re.compile(r"(kırmızı|sarı)\s*kart.*(olur|çıkar|mı|mi)", re.I),
            # Conversational / slang
            re.compile(r"(kaç\s*tane\s*gol|ne\s*kadar\s*gol)", re.I),
            re.compile(r"gol.*(yağar|patlat|bombard)", re.I),
            re.compile(r"(skor\s*ne\s*olur|nasıl\s*bir\s*skor)", re.I),
            re.compile(r"(tahminin\s*ne|ne\s*tahmin\s*edersin)", re.I),
        ],
        keywords=["gol", "kaç gol", "toplam gol", "fazla gol", "skor"],
    ),

    # both_teams_score — "İki takım da gol atar mı?", "KG var mı?"
    IntentPattern(
        intent_id="both_teams_score",
        patterns=[
            re.compile(r"(iki|her\s*iki)\s*(takım|takim)\s*(da|de)?.*gol", re.I),
            re.compile(r"(kg|karşılıklı\s*gol)\s*(var|olur|çıkar)\s*(mı|mi|mu|mü)?", re.I),
            re.compile(r"(iki\s*taraf|her\s*iki\s*taraf).*(gol|skor)", re.I),
            re.compile(r"(iki\s*ekip|iki\s*taraf).*(ağ|skor)", re.I),
            re.compile(r"(hem\s*ev\s*sahibi\s*hem\s*deplasman)\s*(gol)", re.I),
            re.compile(r"(karşılıklı)\s*(gol)\s*(atar|olur|çıkar|bekleniyor)", re.I),
            re.compile(r"(bir\s*taraf|bir\s*takım)\s*(gol\s*atamaz)", re.I),
            re.compile(r"(rakibine)\s*(gol\s*atacak|gol\s*atar)", re.I),
            # Colloquial / shorthand
            re.compile(r"\b(btts|bts)\b", re.I),
            re.compile(r"(iki\s*taraftan\s*da\s*gol)", re.I),
            re.compile(r"(herkes\s*gol\s*atar|ikisi\s*de\s*gol)", re.I),
            re.compile(r"(gol\s*atışır|birbirine\s*gol)", re.I),
        ],
        keywords=["kg", "karşılıklı gol", "iki takım", "her iki taraf"],
    ),

    # clean_sheet — "Gol yemez mi?", "Kale kapanır mı?"
    IntentPattern(
        intent_id="clean_sheet",
        patterns=[
            re.compile(r"(gol)\s*(yemez|yemeden|yemedi|yedirmez)\s*(mi|mı|mu|mü)?", re.I),
            re.compile(r"(kale)\s*(kapanır|kapanir|kapatır|korur)\s*(mı|mi|mu|mü)", re.I),
            re.compile(r"(sıfır|0)\s*(gol|skor).*(biter|kalır)", re.I),
            re.compile(r"(kalesini).*(korur|kapatır|kapatabilir|gol\s*ye)", re.I),
            re.compile(r"(defans\w*|savunma\w*)\s*(sağlam|güçlü|yeterli|hattı)", re.I),
            re.compile(r"(clean\s*sheet)", re.I),
            re.compile(r"(gol\s*yemeden)\s*(çık|bitir|maç)", re.I),
            re.compile(r"kaç\s*kez\s*(kalesini|gol\s*yemeden)", re.I),
        ],
        keywords=["yemez", "kale kapanır", "sıfır gol", "clean sheet", "kalesini"],
    ),

    # half_time — "İlk yarı nasıl biter?", "İlk yarıda gol olur mu?"
    IntentPattern(
        intent_id="half_time",
        patterns=[
            re.compile(r"(ilk|birinci|1\.?)\s*(yarı|yari)\s*(nasıl|da|de|sonucu)", re.I),
            re.compile(r"(ikinci|2\.?)\s*(yarı|yari)\s*(nasıl|da|de|sonucu)", re.I),
            re.compile(r"(devre\s*arası|ilk\s*yarı).*(gol|skor|sonuç)", re.I),
            re.compile(r"(ilk\s*45|ilk\s*15|son\s*10)\s*(dakika)", re.I),
            re.compile(r"(ilk\s*yarıda|ikinci\s*yarıda)\s*(gol|skor|fark|daha|dönüş)", re.I),
            re.compile(r"(ilk\s*yarı)\s*.*(önde|geride|golsüz)", re.I),
            re.compile(r"(devre)\s*(skoru|arası|sonucu)", re.I),
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
            re.compile(r"(istikrarlı|formda|düşüşte|yükselişte)\s*(mı|mi|mu|mü)", re.I),
            re.compile(r"(iç\s*saha|dış\s*saha|evinde|deplasmanında).*(güçlü|nasıl|iyi|kötü)", re.I),
            re.compile(r"(kaçıncı\s*sıra|lig\s*sırala|puan\s*durumu)", re.I),
            re.compile(r"(şampiyon|küme\s*düş|avrupa\s*kupa)", re.I),
            re.compile(r"(gol\s*krallığı|asist|bu\s*sezon\s*kaç)", re.I),
            re.compile(r"(sakatlık|sakat|kadroda|oynar\s*mı)", re.I),
            re.compile(r"(performansı|formu)\s*(nasıl|nedir|ne\s*durumda)", re.I),
            re.compile(r"(ne\s*zaman|son)\s*(galibiyet|mağlubiyet)", re.I),
            re.compile(r"(bu\s*sezon|sezon\s*başından)\s*(nasıl|kaç|ne)", re.I),
            re.compile(r"(kötü|iyi)\s*(bir)?\s*(dönem|form|süreç)", re.I),
            re.compile(r"(hedef|puan\s*fark|kalan\s*maç)", re.I),
            re.compile(r"(ligde|sırada|kaçıncı)\s*(mı|mi|mu|mü|nasıl|nerede)", re.I),
            re.compile(r"(averaj|gol\s*ortalaması|yediği\s*gol|attığı\s*gol)", re.I),
            re.compile(r"(maçın\s*yıldızı|penaltıları|kaç\s*(gol|asist))", re.I),
            # Colloquial / situational
            re.compile(r"(takım|takim|lig|puan|form|kadrо).*?(durumu|durumları)\s*(ne|nasıl|nedir)", re.I),
            re.compile(r"(ne\s*halde|ne\s*alemde)", re.I),
            re.compile(r"(son\s*\d+\s*maç|son\s*hafta).*(nasıl|ne)", re.I),
            re.compile(r"(çöktü\s*mü|dağıldı\s*mı|toparlıyor\s*mu)", re.I),
            re.compile(r"(morali|motivasyonu)\s*(nasıl|iyi|kötü|bozuk|yüksek)", re.I),
            re.compile(r"(kadro|11|on\s*bir).*(kim|nasıl|belli)", re.I),
        ],
        keywords=["form", "performans", "nasıl oynuyor", "gidiyor", "sezon"],
    ),

    # head_to_head — "Bu iki takım son maçlarda nasıl oynadı?"
    IntentPattern(
        intent_id="head_to_head",
        patterns=[
            re.compile(r"(kafa\s*kafaya|karşılaşma|son\s*maçlar)", re.I),
            re.compile(r"(iki\s*takım|aralarında).*(maç|karşılaşma|oynadı)", re.I),
            re.compile(r"(son|önceki)\s*(karşılaşma|maçlar)", re.I),
            re.compile(r"(h2h|rekabet|geçmiş)", re.I),
            re.compile(r"(son\s*\d+\s*(maç|karşılaşma))", re.I),
            re.compile(r"(kaç\s*kez\s*(kazandı|yendi|galip))", re.I),
            # Colloquial
            re.compile(r"(önceki\s*maç|geçen\s*maç).*(ne|nasıl|kaç)", re.I),
            re.compile(r"(birbirini|birbiriyle).*(yen|gol|maç|oynad)", re.I),
            re.compile(r"(geçen\s*sezon|önceki\s*sezon).*(nasıl|ne)", re.I),
        ],
        keywords=["kafa kafaya", "karşılaşma", "son maçlar", "aralarında", "h2h"],
    ),

    # score_predict — "Bu maç kaça kaç biter?", "Skor tahmini ne?"
    IntentPattern(
        intent_id="score_predict",
        patterns=[
            re.compile(r"(kaça?\s*kaç)\s*(biter|olur|tahmin)", re.I),
            re.compile(r"(skor\s*tahmin|tahmin\s*skor)\w*\s*(ne|nedir|eder)?", re.I),
            re.compile(r"(final\s*skor|maç\s*skor)\w*\s*(ne|kaç|nasıl)", re.I),
            re.compile(r"(\d+)\s*[-–]\s*(\d+)\s*(biter|olur|mi|mı|mu|mü)", re.I),
            re.compile(r"(maç|mac)\s*(\d+)\s*[-–]\s*(\d+)", re.I),
            re.compile(r"(tahmin\s*et|tamin\s*et|ne\s*dersin)\s*.*(skor|maç|mac)", re.I),
            re.compile(r"(ne\s*biter|nasıl\s*biter)\s*bu\s*maç", re.I),
            re.compile(r"(sonuç|sonuc)\s*(ne\s*olur|tahmin)", re.I),
        ],
        keywords=["skor", "kaça kaç", "tahmin", "biter", "sonuç"],
        weight=1.1,  # slight boost — specific request
    ),
]

# Quick lookup
INTENT_MAP: dict[str, IntentPattern] = {p.intent_id: p for p in INTENT_PATTERNS}
