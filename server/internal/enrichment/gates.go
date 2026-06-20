package enrichment

// Plane constants for enrichment planes
const (
	PlaneRoster     = "roster"      // Plane 6
	PlaneHealth     = "health"      // Plane 7
	PlaneOfficials  = "officials"   // Plane 8
	PlaneEnvironment = "environment" // Plane 9
)

// EnrichmentAllowed checks if a tier is entitled to access an enrichment plane.
// Returns false for unknown tiers (deny-by-default security model).
func EnrichmentAllowed(tier UserTier, plane string) bool {
	switch tier {
	case TierFree:
		// Free tier has no enrichment access
		return false
	case TierPro:
		// Pro tier allows officials and environment planes only
		return plane == PlaneOfficials || plane == PlaneEnvironment
	case TierPremium:
		// Premium tier allows all planes
		return true
	default:
		// Unknown tier is always denied
		return false
	}
}

// Tests for the gates module (would normally be in gates_test.go)
// Included here for Phase 21.18 verification
