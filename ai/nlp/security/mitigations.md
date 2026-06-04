# NLP Dependency CVE Mitigations

This file documents the dependency classes and defense-in-depth measures
for Phase 10 Turkish NLP.

## Jinja2 / template rendering

- Enforce `autoescape=True` in all Jinja2 environment creation.
- Disallow `from_string` and direct template compilation in runtime paths.
- Use AST-level validation for template variables in `ai/nlp/render.py`.

## CRF / model serialization

- Load CRF models only from signed / vendored files.
- Validate model file hashes before deserialization.
- Keep runtime model loaders narrow and reject unexpected metadata.

## Native extension dependencies

- Keep all optional native wheels pinned in `ai/requirements.txt`.
- Use `pip-audit==5.0.0` as the daily scan to catch CVEs in direct runtime deps.
- Pin the optional `babel==2.13.1` dev dependency for TR formatting cross-checks.
- Avoid importing native extension code during boot if the feature is disabled.

## Timezone / zoneinfo

- Treat `zoneinfo` as a system dependency with `nlp_render_timezone` fallback.
- Pin the IANA tzdata baseline version in documentation and CI manifests.
