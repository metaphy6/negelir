// Package authz implements Phase 9 coarse-grained authorization checks that
// run after authentication (server/internal/auth JWT verification) and before
// the business handler.
//
// Rules are data-driven: a role bitmap is stored per user in
// migrations/012_users_and_sessions.sql and checked here. Fine-grained checks
// (e.g. match ownership) belong in the handler, not here.
//
// Tier enforcement (cfg.api_tier_enforcement_enabled) is handled by the
// TierQuota middleware in server/internal/middleware; authz handles only
// role-based access control.
package authz
