-- Phase 21.25 -- Enrichment Compliance Audit Log
-- Append-only audit trail for jurisdiction-gating decisions per league and plane.

CREATE TABLE enrichment_audit (
    id            BIGSERIAL PRIMARY KEY,
    event_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    league_id     TEXT NOT NULL,
    jurisdiction  TEXT NOT NULL,          -- 'gdpr' | 'kvkk' | 'lgpd' | 'pipl' | 'unrestricted'
    plane_id      TEXT NOT NULL,          -- 'roster' | 'health' | 'officials' | 'environment'
    decision      TEXT NOT NULL,          -- 'allow' | 'suppress'
    reason        TEXT NOT NULL,          -- 'dpa_active' | 'no_dpa' | 'unrestricted' | 'officials_exempt'
    dpa_status    TEXT,                   -- snapshot of dpa_registry.yaml status at decision time
    operator_ref  TEXT                    -- optional: reference to operator ticket / approval
);

-- Enforce append-only at row security level
REVOKE UPDATE, DELETE ON enrichment_audit FROM negelir_app;

-- Index for audit queries by league and plane
CREATE INDEX idx_enrichment_audit_league_plane ON enrichment_audit(league_id, plane_id, event_at DESC);
CREATE INDEX idx_enrichment_audit_jurisdiction ON enrichment_audit(jurisdiction, event_at DESC);

-- Track schema version
COMMENT ON TABLE enrichment_audit IS 'Phase 21.25: Append-only audit trail for jurisdiction-gating decisions. Never modified after insert.';
