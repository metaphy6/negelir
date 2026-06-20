"""
Negelir TRC — Pre-written Turkish response templates.
Per roadmap §5.1: all Turkish text is pre-written by a native speaker.
The AI never generates novel Turkish text.
"""

# ── Verdict templates (per roadmap TRC verdict selection) ──

VERDICTS = {
    "strong_yes":    "Büyük ihtimalle evet.",
    "strong_no":     "Büyük ihtimalle hayır.",
    "likely_yes":    "Muhtemelen evet, ama kolay değil.",
    "likely_no":     "Muhtemelen hayır, ama sürpriz olabilir.",
    "uncertain":     "Zor bir tahmin.",
    "balanced":      "İki taraf için de argüman var.",
    "low_data":      "Bu maç için yeterli veri yok, dikkatli olmak gerek.",
    # Phase 2: data-quality verdicts
    "fixture_unknown":     "Belirtilen maç fikstürde bulunamadı.",
    "data_stale":          "Veriler güncel değil, tahmin güvenilirliği düşük.",
    "insufficient_data":   "Bu takım için yeterli geçmiş veri bulunmuyor.",
}

# ── Rejection messages (fixed, per roadmap §5.6.2) ──────

REJECTIONS = {
    "no_football":   "Sadece futbol maçları hakkında sorulara cevap verebilirim. Maç sonucu, gol sayısı, alt/üst, veya takım formu gibi konularda sorabilirsiniz.",
    "no_intent":     "Sorunuzu anlayamadım. Maç sonucu, gol sayısı, alt/üst, karşılıklı gol veya takım formu hakkında sorabilirsiniz.",
    "no_team":       "Hangi takım veya maç hakkında sorduğunuzu anlayamadım. Lütfen takım adını belirtin.",
}

# ── Explanation templates per intent ─────────────────────
# {placeholders} are filled by the TRC composer from model output.
# Per roadmap: each template references feature importance data.

EXPLANATION_TEMPLATES = {
    "match_winner": {
        "strong_yes": (
            "{team} son {window} maçının {win_count}'ini kazanmış ve genel form endeksi yükselişte. "
            "Rakip takımın {venue_type} performansı zayıf — son {window} {venue_type_tr}da sadece "
            "{opp_wins} galibiyet var. Kafa kafaya istatistiklerde de {advantage_text}. "
            "Güven: %{confidence}."
        ),
        "strong_no": (
            "{team} son {window} maçta sadece {win_count} galibiyet almış ve form endeksi düşüşte. "
            "Rakip takımın {venue_type} performansı güçlü — son {window} maçta {opp_wins} galibiyet. "
            "{momentum_text} Güven: %{confidence}."
        ),
        "likely_yes": (
            "{team} son dönemde iyi form yakalamış, ancak rakip de zayıf sayılmaz. "
            "İstatistikler hafif {team} lehine ama fark büyük değil. "
            "{h2h_text} Güven: %{confidence}."
        ),
        "likely_no": (
            "Veriler {team} için zorlayıcı görünüyor. Rakip takım son dönemde daha iyi sonuçlar almış. "
            "Ancak futbolda sürprizler her zaman mümkün. {h2h_text} Güven: %{confidence}."
        ),
        "uncertain": (
            "Her iki takımın formu birbirine yakın ve istatistiksel veriler net bir yöne işaret etmiyor. "
            "{h2h_text} Güven: %{confidence}."
        ),
    },
    "draw": {
        "strong_yes": (
            "Son verilere göre iki takımın güç dengesi birbirine çok yakın. "
            "Son {window} maçta beraberlik oranı %{draw_pct} civarında ve her iki takım da "
            "dengeli bir performans sergiliyor. {momentum_text} Güven: %{confidence}."
        ),
        "strong_no": (
            "İki takım arasında belirgin bir güç farkı var. Son {window} karşılaşmada "
            "beraberlik oranı düşük (%{draw_pct}). {momentum_text} Güven: %{confidence}."
        ),
        "uncertain": (
            "Her iki takımın formu birbirine yakın ve istatistiksel veriler net bir yöne "
            "işaret etmiyor. Son {window} maçta beraberlik oranı %{draw_pct} civarında — "
            "olabilir ama kesinlik yok. Güven: %{confidence}."
        ),
    },
    "over_under": {
        "strong_yes": (
            "Son verilere göre iki takımın son {window} maçtaki ortalama toplam gol sayısı {avg_goals}. "
            "{defense_text} İki takımın karşılaşma geçmişinde maçların %{h2h_over_pct}'i üst bitmiş. "
            "{momentum_text} Güven: %{confidence}."
        ),
        "strong_no": (
            "Son verilere göre iki takımın son {window} maçtaki ortalama toplam gol sayısı {avg_goals}. "
            "{defense_text} Bu maçta {threshold_text} beklentisi düşük. Güven: %{confidence}."
        ),
        "likely_yes": (
            "İstatistikler hafif üst yönünde. Son {window} maçta ortalama {avg_goals} gol var. "
            "{defense_text} Güven: %{confidence}."
        ),
        "likely_no": (
            "Son maçlardaki eğilim alt yönünde. Ortalama gol sayısı {avg_goals} ve "
            "iki takımın da defansif eğilimleri güçlü. Güven: %{confidence}."
        ),
        "uncertain": (
            "Gol istatistikleri karışık. Ortalama {avg_goals} gol ile sınırda bir durum. "
            "Hava koşulları ve saha durumu da etkili olabilir. Güven: %{confidence}."
        ),
    },
    "goal_range": {
        "strong_yes": (
            "Son {window} maçtaki gol dağılımına bakıldığında {min_goals}-{max_goals} gol aralığı "
            "gerçekçi görünüyor. Ortalama toplam gol {avg_goals} ve bu aralık dağılım içinde. "
            "Güven: %{confidence}."
        ),
        "strong_no": (
            "Son verilere göre ortalama toplam gol sayısı {avg_goals}. "
            "{min_goals}-{max_goals} gol aralığı bu ortalamanın {direction} ve olasılığı düşük. "
            "Güven: %{confidence}."
        ),
        "uncertain": (
            "Gol dağılımı geniş bir aralıkta seyrediyor. Ortalama {avg_goals} gol ile "
            "{min_goals}-{max_goals} aralığı mümkün ama kesin değil. Güven: %{confidence}."
        ),
    },
    "both_teams_score": {
        "strong_yes": (
            "Son {window} maçta her iki takım da maçların %{bts_pct}'inde gol bulmuş. "
            "Her iki takımın ofansif istatistikleri güçlü ve defansif açıkları mevcut. "
            "Güven: %{confidence}."
        ),
        "strong_no": (
            "Son verilere göre karşılıklı gol oranı düşük (%{bts_pct}). "
            "{defense_text} Güven: %{confidence}."
        ),
        "uncertain": (
            "Karşılıklı gol istatistikleri karışık (%{bts_pct}). Bir takımın ofansı güçlü "
            "ama diğerinin defansı da sağlam. Güven: %{confidence}."
        ),
    },
    "clean_sheet": {
        "strong_yes": (
            "{team} son {window} maçta {clean_sheets} kez kalesini kapattı. "
            "Defans organizasyonu güçlü ve rakip takımın gol bulma oranı düşük. "
            "Güven: %{confidence}."
        ),
        "strong_no": (
            "{team} son {window} maçta sadece {clean_sheets} kez kapısını kapattı. "
            "Defansif istatistikler kale kapama için olumsuz. Güven: %{confidence}."
        ),
        "uncertain": (
            "Kale kapama istatistikleri dengeli. Son {window} maçta {clean_sheets} clean sheet var. "
            "Güven: %{confidence}."
        ),
    },
    "half_time": {
        "strong_yes": (
            "{half_text} istatistikleri incelendiğinde, son {window} maçta {half_stat}. "
            "İki takımın da {half_text_lower} performansı bu yönde. Güven: %{confidence}."
        ),
        "uncertain": (
            "{half_text} sonuçları değişken. Son {window} maçta net bir eğilim yok. "
            "Güven: %{confidence}."
        ),
    },
    "form_query": {
        "report": (
            "{team} son {window} maçta {wins} galibiyet, {draws} beraberlik, {losses} mağlubiyet almış. "
            "Gol ortalaması: {avg_scored} attı, {avg_conceded} yedi. "
            "Form endeksi: {form_label}. Elo puanı: {elo}. "
            "Güven: %{confidence}."
        ),
    },
    "head_to_head": {
        "report": (
            "Son {window} karşılaşmada {team1}: {t1_wins} galibiyet, {team2}: {t2_wins} galibiyet, "
            "{draws} beraberlik. Ortalama toplam gol: {avg_goals}. "
            "Son eğilim: {trend_text}. Güven: %{confidence}."
        ),
    },
    # ── Phase 21 enrichment intent templates ─────────────────────
    "transfer_lookup": {
        "found": (
            "{player_name} {transfer_type} ile {team_name}'ye/ndan {date} tarihinde transfer oldu. "
            "Transfer bedeli: {fee_text}."
        ),
        "not_found": (
            "{player_name} hakkında bu döneme ait transfer bilgisi bulunamadı. "
            "{team_name} transfer piyasasında daha fazla hareket yapamadı."
        ),
    },
    "injury_lookup": {
        "out": (
            "{player_name} ({team_name}) şu an sakatlanmış durumda. "
            "Beklenen dönüş tarihi: {expected_return}. Sakatlanma sebebi: {injury_type}."
        ),
        "doubtful": (
            "{player_name} ({team_name}) şüpheli durumdadır. Maç kaydında yer alabilir "
            "ama son dakikada değişiklik yapılabilir."
        ),
        "fit": (
            "{player_name} ({team_name}) tamamen sağlıklı ve maça hazırdır."
        ),
    },
    "availability_lookup": {
        "available": (
            "{player_name} ({team_name}) bu hafta maça hazır durumdadır."
        ),
        "doubtful": (
            "{player_name} ({team_name}) bu hafta şüpheli durumdadır."
        ),
        "unavailable": (
            "{player_name} ({team_name}) bu hafta maça katılamayacaktır."
        ),
    },
    "referee_lookup": {
        "report": (
            "Hakem: {referee_name}. Son {window} maçta ort. {avg_yellows} sarı, "
            "{avg_reds} kırmızı kart göstermiş. İstatistik: {stat_text}."
        ),
    },
    "weather_lookup": {
        "report": (
            "Maç günü hava durumu: {condition}. Sıcaklık: {temp}°C. "
            "Rüzgar: {wind_kph} km/s. Yağış olasılığı: %{rain_chance}. "
            "Pitch durumu: {pitch_text}."
        ),
    },
    "suspension_lookup": {
        "suspended": (
            "{player_name} ({team_name}) disiplin cezasıdır. "
            "Kalan ceza: {matches_left} maç. Ceza nedeni: {reason}."
        ),
        "not_suspended": (
            "{player_name} ({team_name}) ceza durumunda değildir."
        ),
    },
}


# ── Momentum sentence fragments ─────────────────────────
MOMENTUM_SENTENCES = {
    "both_rising":       "Ayrıca her iki takımın da son maçlardaki ofansif formu yükselişte.",
    "home_rising":       "Ev sahibinin son maçlardaki formu yükselişte.",
    "away_rising":       "Deplasman takımının son maçlardaki formu yükselişte.",
    "both_falling":      "Her iki takımın da son dönem performansı düşüşte.",
    "home_falling":      "Buna karşın ev sahibinin son iç saha performansı düşüşte.",
    "away_falling":      "Ancak deplasman takımının son maçlardaki gol ortalaması düşüyor.",
    "stable":            "İki takımın da formu son dönemde istikrarlı.",
    "consensus":         "Diğer analizlerle de uyumlu bir sonuç.",
    "against_consensus": "Ancak bu tahmin genel konsensüsten farklı.",
}

DEFENSE_SENTENCES = {
    "strong":    "Ev sahibinin defansı son dönemde güçlü ve son 5 maçta az gol yemiş.",
    "weak":      "Her iki takımın da defansif istatistikleri zayıf.",
    "mixed":     "Bir takımın defansı güçlü, diğerininki tartışmalı.",
    "both_good": "Her iki takımın da defansı sağlam, gol bulmak zor olabilir.",
}

H2H_SENTENCES = {
    "home_dominant":   "Kafa kafaya istatistiklerde ev sahibi açık ara önde.",
    "away_dominant":   "Kafa kafaya istatistiklerde deplasman takımı üstün.",
    "balanced":        "Kafa kafaya istatistikler dengeli.",
    "no_data":         "Yeterli kafa kafaya veri bulunmuyor.",
}

FORM_LABELS = {
    "excellent":  "Mükemmel",
    "good":       "İyi",
    "average":    "Orta",
    "poor":       "Zayıf",
    "very_poor":  "Çok Zayıf",
}
