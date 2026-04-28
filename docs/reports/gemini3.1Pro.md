# Negelir Project Review - Gemini 3.1 Pro (Preview)

*Date: April 28, 2026*

## 1. Executive Summary
This report provides a high-level review of the `negelir` project, focusing on architecture, performance, efficiency, and potential misalignments with the project's strict doctrine (as defined in `AGENTS.md` and `ROADMAP.md`).

## 2. Issues & Mistakes (Strict Doctrine Violations)
*   **Fabricated Data Risks:** Ensure that no synthetic data generation (e.g., `ai/tests/generate_test_data.py`) leaks into production namespaces. The `ROADMAP.md` dictates "No fabricated production data".
*   **Database/Memory Isolation:** The project enforces "Scale symmetry: State lives in Redis / Postgres, never in process memory." Ensure modules like `ai/orchestrator/state_machine.py` or cache reactors do not hold local in-memory dictionaries that cause inconsistency across Swarm agent replicas.
*   **Security Restrictions:** Scripts in `xops/makefile/` and CI tools should not invoke `git` automatically in a way that violates rule 9 ("Git is the only AI-restricted surface"). 

## 3. Architectural Improvements
*   **Scraper Self-Healing (Phase 17 context):** The scraper engine (`ai/scraper/engine.py` and `self_healing.py`) can quickly become a bottleneck if regex or DOM selectors change. Ensure the auto-patcher harness (`CLAUDE.md`) is heavily rate-limited and fails fast to prevent runaway API costs or infinite loops.
*   **Swarm Backpressure:** As agents scale up, the inter-process messaging (likely Redis pubsub or NATS) might drop messages during sudden spikes (e.g., weekend match days). Implement strict backpressure mechanisms in `ai/swarm/sdk/` and `ai/pipeline/runner.py`.

## 4. Performance & Efficiency
*   **Model Sizing:** The rule "Smallest model that works" is excellent. For `ai/model/inference.py` and `nlp/sentiment.py`, ensure that scikit-learn/XGBoost are preferred over LLMs for discrete regression or classification tasks (e.g., odds prediction). Save LLMs strictly for unstructured text/NLP tasks where deterministic logic fails.
*   **Database Migrations:** The `migrations/` folder is currently sequential (`001_initial.sql`, `002_players.sql`). As the application scales, naive `ALTER TABLE` statements on multi-gigabyte historical data tables can lock the database for minutes/hours in Postgres. Switch to concurrent indexing and batched data migrations.
*   **Test Suite Efficiency:** Running `make test.ai` might become slow as historical prediction tests (`historical_prediction_test.py`) grow. Partition tests into unit (`test_unit.py`) and slow integration suites to keep CI feedback loops under 2 minutes.

## 5. Wrong Assumptions to Avoid
*   **Constant Upstream Availability:** Assuming `mackolik` or `tff` websites will respond within 500ms or maintain the same DOM structure is a critical risk. The `ai/scraper/health.py` must decouple upstream failures from internal cascade failures.
*   **Language Mixing:** Overlooking the "Turkish UX, English infra" rule. Ensure `ai/common/locale_tr.yaml` contains ALL user-facing strings and hardcoded Turkish is systematically scrubbed from Python/Go source files.

## 6. Next Steps
1. Audit `ai/common/config.py` against `xops/env/.env.example` to ensure no configuration drift.
2. Review `ai/orchestrator/state_machine.py` for statelessness/Redis-only state.
3. Track these optimizations via `docs/tracking/track.py` to maintain the project's single-source-of-truth timeline.