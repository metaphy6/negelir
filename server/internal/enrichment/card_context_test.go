package enrichment

import (
	"context"
	"testing"
)

func TestFilterEnrichmentByTier_Free(t *testing.T) {
	ctx := context.Background()

	overlay := &EnrichmentOverlay{
		SquadStrengthDelta:     0.05,
		CohesionPenalty:        0.08,
		RefereeYellowsPerMatch: 4.2,
		WindXGFactor:           1.0,
		CardContext: &CardContextFeatures{
			CombinedCardScore: 0.5,
		},
	}

	filtered := FilterEnrichmentByTier(ctx, overlay, TierFree)

	// Free tier should have no enrichment features
	if filtered.SquadStrengthDelta != 0 || filtered.RefereeYellowsPerMatch != 0 ||
		filtered.WindXGFactor != 0 || filtered.CardContext != nil {
		t.Error("Free tier should have no enrichment features")
	}
}

func TestFilterEnrichmentByTier_Pro(t *testing.T) {
	ctx := context.Background()

	overlay := &EnrichmentOverlay{
		SquadStrengthDelta:     0.05,
		RefereeYellowsPerMatch: 4.2,
		RefereeRedsPerMatch:    0.1,
		WindXGFactor:           1.0,
	}

	filtered := FilterEnrichmentByTier(ctx, overlay, TierPro)

	// Pro tier should have Officials plane only (no squad/wind features)
	if filtered.SquadStrengthDelta != 0 {
		t.Error("Pro tier should not have Roster plane features")
	}
	if filtered.RefereeYellowsPerMatch != 4.2 || filtered.RefereeRedsPerMatch != 0.1 {
		t.Error("Pro tier should have Officials plane features")
	}
	if filtered.WindXGFactor != 0 {
		t.Error("Pro tier should not have Environment plane features")
	}
}

func TestFilterEnrichmentByTier_Premium(t *testing.T) {
	ctx := context.Background()

	overlay := &EnrichmentOverlay{
		SquadStrengthDelta:     0.05,
		RefereeYellowsPerMatch: 4.2,
		WindXGFactor:           1.0,
		CardContext: &CardContextFeatures{
			CombinedCardScore: 0.5,
		},
	}

	filtered := FilterEnrichmentByTier(ctx, overlay, TierPremium)

	// Premium tier should have all enrichment planes
	if filtered.SquadStrengthDelta != 0.05 {
		t.Error("Premium tier should have Roster plane features")
	}
	if filtered.RefereeYellowsPerMatch != 4.2 {
		t.Error("Premium tier should have Officials plane features")
	}
	if filtered.WindXGFactor != 1.0 {
		t.Error("Premium tier should have Environment plane features")
	}
	if filtered.CardContext == nil || filtered.CardContext.CombinedCardScore != 0.5 {
		t.Error("Premium tier should have card-context overlay")
	}
}

func TestTierGateCardContext_Premium(t *testing.T) {
	ctx := context.Background()

	// Premium tier should be allowed card-context
	err := TierGateCardContext(ctx, TierPremium, true)
	if err != nil {
		t.Errorf("Premium tier should allow card-context, got error: %v", err)
	}
}

func TestTierGateCardContext_Pro(t *testing.T) {
	ctx := context.Background()

	// Pro tier should NOT be allowed card-context
	err := TierGateCardContext(ctx, TierPro, true)
	if err == nil {
		t.Error("Pro tier should not allow card-context")
	}
}

func TestTierGateCardContext_Free(t *testing.T) {
	ctx := context.Background()

	// Free tier should NOT be allowed card-context
	err := TierGateCardContext(ctx, TierFree, true)
	if err == nil {
		t.Error("Free tier should not allow card-context")
	}
}

func TestEnrichmentAllowed_Cards_Pro(t *testing.T) {
	ctx := context.Background()

	// Pro tier should allow cards market
	if !EnrichmentAllowed(ctx, "cards", TierPro) {
		t.Error("Pro tier should allow cards market")
	}
}

func TestEnrichmentAllowed_Cards_Free(t *testing.T) {
	ctx := context.Background()

	// Free tier should NOT allow cards market
	if EnrichmentAllowed(ctx, "cards", TierFree) {
		t.Error("Free tier should not allow cards market")
	}
}

func TestEnrichmentAllowed_PlayerProps_Premium(t *testing.T) {
	ctx := context.Background()

	// Premium tier should allow player-props
	if !EnrichmentAllowed(ctx, "player_props", TierPremium) {
		t.Error("Premium tier should allow player-props market")
	}
}

func TestEnrichmentAllowed_PlayerProps_Pro(t *testing.T) {
	ctx := context.Background()

	// Pro tier should NOT allow player-props
	if EnrichmentAllowed(ctx, "player_props", TierPro) {
		t.Error("Pro tier should not allow player-props market")
	}
}

func TestEnrichmentAllowed_WeatherSensitive_Premium(t *testing.T) {
	ctx := context.Background()

	// Premium tier should allow weather-sensitive markets
	if !EnrichmentAllowed(ctx, "weather_sensitive", TierPremium) ||
		!EnrichmentAllowed(ctx, "windy_day_totals", TierPremium) ||
		!EnrichmentAllowed(ctx, "red_card_markets", TierPremium) {
		t.Error("Premium tier should allow weather-sensitive markets")
	}
}

func TestEnrichmentAllowed_WeatherSensitive_Free(t *testing.T) {
	ctx := context.Background()

	// Free tier should NOT allow weather-sensitive markets
	if EnrichmentAllowed(ctx, "weather_sensitive", TierFree) {
		t.Error("Free tier should not allow weather-sensitive markets")
	}
}

func TestEnrichmentAllowed_Standard_Free(t *testing.T) {
	ctx := context.Background()

	// Free tier should allow standard markets (1x2, over/under, etc.)
	if !EnrichmentAllowed(ctx, "1x2", TierFree) ||
		!EnrichmentAllowed(ctx, "over_under", TierFree) {
		t.Error("Free tier should allow standard markets")
	}
}
