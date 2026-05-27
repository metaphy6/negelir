// Package auth implements Phase 9 identity and session management.
//
// Responsibilities:
//   - User registration (behind cfg.api_self_registration_enabled flag)
//   - Login: issues access token (15 min) + refresh token (30 d, rotated on use)
//   - Refresh: rotates the refresh token; old token blacklisted in Redis
//   - Logout: revokes the refresh token; access tokens expire naturally
//   - JWT key lifecycle: RS256 keys stored in migrations/014_jwt_keys.sql;
//     sealed key material loaded from data/api/ (mode 0400)
//
// This package MUST NOT re-implement any sanitizer, pattern engine, or rate
// limiter already provided by server/internal/sec (Phase 7 doctrine §9.0 §7).
package auth
