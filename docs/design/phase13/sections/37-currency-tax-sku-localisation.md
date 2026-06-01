# Phase 13.37 — Currency, tax & SKU localisation

> Extracted from `docs/planning/ROADMAP.md` §13.37
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.37 Currency, tax & SKU localisation

> Retires assumption §13.0 #44. Phase 20 dormant; the data model
> ships now to avoid retrofit pain.

- [ ] **Per-row fields.** `LeagueRow.currency: ISO-4217`, `tax_jurisdiction: str`, `sku_price_band: enum {budget, standard, premium, enterprise}`, `vat_rate_pct: float`.
- [ ] **Phase 20 entitlement reads catalog.** `entitlements.yaml` references `LeagueRow.sku_price_band` (not raw price); per-tier prices live in `xops/monetization/sku_prices.yaml`. Lint refuses a hardcoded price in `entitlements.yaml`.
- [ ] **Multi-currency display.** Phase 9 `/v1/catalog` surfaces per-row currency; Phase 15 frontend shows the localised currency by default with a manual override.
- [ ] **VAT-rate snapshot.** Per-jurisdiction `vat_rate_pct` snapshot date stored alongside; VAT changes require a tracker row + chart bump (`xops/lint/sku_vat_lifecycle.py`).
- [ ] **Sandbox immunity.** §13.43 sandbox league bypasses all currency / VAT logic — never charged.
