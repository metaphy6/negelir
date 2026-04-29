---
description: Audit a module for AGENTS.md Rule 1 (single-source config) violations.
mode: ask
---

Audit the file or folder I name (or my current selection) for
**single-source-config violations** per
[`AGENTS.md`](../../AGENTS.md) Rule 1.

Look for:

- Magic numbers that should be in `ai/common/config.py`,
  `server/internal/config`, or a `defaults.yaml`.
- Hardcoded URLs, hostnames, ports, or paths.
- Inline thresholds (timeouts, retry counts, batch sizes, model
  hyper-parameters, log-rotation sizes…).
- Env-var reads (`os.environ`, `os.getenv`, `os.Getenv`) that
  bypass the config layer.
- Strings that look like secrets or tokens.

For each finding, report:

- `file:line` — the violation
- **Why it's a violation** — quote the relevant doctrine line
- **Suggested fix** — name the config key, the
  `xops/env/.env.example` entry to add, and the loader call site

Do **not** edit any file. End with a summary count of findings
by severity (high / medium / low). Cite every claim.
