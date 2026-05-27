package api

// ResolveProfileID maps a league ID to the profile_id that is stamped on every
// bus envelope produced by the API layer.
//
// Phase 13a contract: when the catalog is live, this function's body will be
// replaced by a catalog-driven lookup with zero handler diffs. All handlers
// MUST obtain the profile_id exclusively through this function; the boundary
// test in contracts_test.go enforces that invariant via AST scan.
func ResolveProfileID(leagueID string) string {
	// Phase 9: profile_id == leagueID (identity mapping).
	// Phase 13a replaces only this body with a catalog lookup.
	return leagueID
}
