package enrichment

import (
	"context"
	"fmt"
)

// UserTier represents the subscription tier of a user (free, pro, premium).
type UserTier string

const (
	TierFree    UserTier = "free"
	TierPro     UserTier = "pro"
	TierPremium UserTier = "premium"
)

// CardContextFeatures represents the card-context enrichment overlay.
type CardContextFeatures struct {
	CombinedCardScore            float64 `json:"combined_card_score"`
	RefereeCardsPerMatchSmoothed float64 `json:"referee_cards_per_match_smoothed"`
}

// EnrichmentOverlay groups all enrichment-derived market features.
type EnrichmentOverlay struct {
	// Plane 6 (Roster)
	SquadStrengthDelta  float64 `json:"squad_strength_delta,omitempty"`
	CohesionPenalty     float64 `json:"cohesion_penalty,omitempty"`
	DepartureShock      float64 `json:"departure_shock,omitempty"`

	// Plane 7 (Health)
	SquadAvailabilityScore float64 `json:"squad_availability_score,omitempty"`
	DoubtfulRatio          float64 `json:"doubtful_ratio,omitempty"`
	KeyPlayerOutFlag       bool    `json:"key_player_out_flag,omitempty"`

	// Plane 8 (Officials)
	RefereeYellowsPerMatch   float64 `json:"referee_yellows_per_match,omitempty"`
	RefereeRedsPerMatch      float64 `json:"referee_reds_per_match,omitempty"`
	RefereePenaltiesPerMatch float64 `json:"referee_penalties_per_match,omitempty"`
	RefereeHomeWinPctAdj     float64 `json:"referee_home_win_pct_adj,omitempty"`

	// Plane 9 (Environment)
	WindXGFactor        float64 `json:"wind_xg_factor,omitempty"`
	RainXGFactor        float64 `json:"rain_xg_factor,omitempty"`
	SurfaceStylePenalty float64 `json:"surface_style_penalty,omitempty"`
	PitchConditionScore float64 `json:"pitch_condition_score,omitempty"`

	// Card-context overlay (Plane 8 derived)
	CardContext *CardContextFeatures `json:"card_context,omitempty"`
}

// FilterEnrichmentByTier returns the enrichment overlay filtered by user tier.
// Rules (per §21.12):
//   - free: no enrichment features (empty overlay)
//   - pro: cards/corners/fouls markets only (Officials plane + fixture-congestion)
//   - premium: all enrichment planes (player-props, weather-sensitive, card-context)
func FilterEnrichmentByTier(ctx context.Context, overlay *EnrichmentOverlay, userTier UserTier) *EnrichmentOverlay {
	if overlay == nil {
		return nil
	}

	filtered := &EnrichmentOverlay{}

	switch userTier {
	case TierFree:
		// Free tier: no enrichment features
		return filtered

	case TierPro:
		// Pro tier: Officials plane (plane 8) only
		// Cards/corners/fouls markets require referee data + fixture-congestion
		filtered.RefereeYellowsPerMatch = overlay.RefereeYellowsPerMatch
		filtered.RefereeRedsPerMatch = overlay.RefereeRedsPerMatch
		filtered.RefereePenaltiesPerMatch = overlay.RefereePenaltiesPerMatch
		filtered.RefereeHomeWinPctAdj = overlay.RefereeHomeWinPctAdj
		// Note: fixture-congestion derived view not implemented yet (Phase 21.5)
		return filtered

	case TierPremium:
		// Premium tier: all enrichment planes
		// Player-props (Roster + Health planes)
		filtered.SquadStrengthDelta = overlay.SquadStrengthDelta
		filtered.CohesionPenalty = overlay.CohesionPenalty
		filtered.DepartureShock = overlay.DepartureShock
		filtered.SquadAvailabilityScore = overlay.SquadAvailabilityScore
		filtered.DoubtfulRatio = overlay.DoubtfulRatio
		filtered.KeyPlayerOutFlag = overlay.KeyPlayerOutFlag
		// Officials plane
		filtered.RefereeYellowsPerMatch = overlay.RefereeYellowsPerMatch
		filtered.RefereeRedsPerMatch = overlay.RefereeRedsPerMatch
		filtered.RefereePenaltiesPerMatch = overlay.RefereePenaltiesPerMatch
		filtered.RefereeHomeWinPctAdj = overlay.RefereeHomeWinPctAdj
		// Environment plane (weather-sensitive markets)
		filtered.WindXGFactor = overlay.WindXGFactor
		filtered.RainXGFactor = overlay.RainXGFactor
		filtered.SurfaceStylePenalty = overlay.SurfaceStylePenalty
		filtered.PitchConditionScore = overlay.PitchConditionScore
		// Card-context overlay (tier-gated here, computed in AI layer)
		filtered.CardContext = overlay.CardContext
		return filtered

	default:
		// Unknown tier: default to free
		return &EnrichmentOverlay{}
	}
}

// TierGateCardContext enforces tier restrictions on card-context overlay.
// Returns an error if the user tier does not permit card-context features.
// This gate is enforced in the Go API, not in the AI pipeline (which always computes it).
func TierGateCardContext(ctx context.Context, userTier UserTier, hasCardContext bool) error {
	// Card-context overlay requires premium tier
	if !hasCardContext {
		return nil  // No card context to gate
	}

	if userTier != TierPremium {
		return fmt.Errorf(
			"card-context overlay requires premium tier (user has %s)",
			userTier,
		)
	}

	return nil
}

// EnrichmentAllowed checks if a user is entitled to enrichment features for a given market family.
// Returns true if the market is accessible to the user's tier; false otherwise.
//
// Market families and tier requirements (per §21.12):
//   - cards/corners/fouls: pro
//   - player-props: premium
//   - weather-sensitive (windy_day_totals, red_card_markets): premium
//   - standard markets (1x2, over/under, etc.): free
func EnrichmentAllowed(ctx context.Context, marketFamily string, userTier UserTier) bool {
	switch marketFamily {
	case "cards", "corners", "fouls":
		// Pro tier gate
		return userTier == TierPro || userTier == TierPremium

	case "player_props":
		// Premium tier gate
		return userTier == TierPremium

	case "weather_sensitive", "windy_day_totals", "red_card_markets":
		// Premium tier gate
		return userTier == TierPremium

	default:
		// Standard markets: free tier access
		return true
	}
}
