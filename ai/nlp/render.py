"""Phase 10 \u00a710.7 \u2014 Jinja2 rendering environment for Turkish NLP answers.

Exposes :func:`build_environment` to construct a shared ``jinja2.Environment``
and :func:`render` as a convenience wrapper.

Design choices (\u00a710.7 binding):

* ``autoescape=False``: output is plain Turkish text; XSS escaping lives at the
  API serialization layer (Phase 9 \u00a79.4), not in the template engine.
* ``undefined=jinja2.StrictUndefined``: any missing template slot raises
  ``jinja2.UndefinedError`` immediately.  The caller catches it and routes the
  request to the ``meta.unsupported`` template; empty strings from missing
  slots are NEVER acceptable.
* All custom Turkish morphology filters from :mod:`nlp.jinja_filters_tr` are
  registered (``dative``, ``accusative``, ``locative``, ``ablative``,
  ``genitive``, ``plural``, ``kickoff_time``, ``match_label``).
* The ``confidence_band`` filter is bound via a closure that captures
  ``cfg.nlp_confidence_bands`` so templates may call
  ``{{ prob | confidence_band }}`` without an extra argument.
"""
from __future__ import annotations

import hashlib
import datetime as dt
import html
import json
import pathlib
import re
import unicodedata
from typing import Any

import jinja2
import jinja2.bccache

from nlp.jinja_filters_tr import FILTERS, confidence_band, kickoff_time


# ---------------------------------------------------------------------------
# §10.21.6 Runtime guard exception
# ---------------------------------------------------------------------------
class RawUserTextInTemplateError(jinja2.TemplateError):
    """Raised by finalize when a rendered slot contains raw user input.
    
    This is the runtime 'shouldn't happen' alarm — the AST lint should
    catch these cases at build time. When this fires, it indicates either:
    - A template bypassed the AST lint
    - A logic bug in slot construction that injects user text at runtime
    
    The caller must emit nlp.alert.v1{kind=nlp_template_render_used_raw_user_text,
    severity=critical} and block the answer.
    """
    
    def __init__(self, matched_substring: str, original_text: str) -> None:
        self.matched_substring = matched_substring
        self.original_text = original_text
        super().__init__(
            f"Template slot contains raw user input substring: {matched_substring[:50]!r}"
        )

# Canonical template directory: sibling ``templates/`` folder of this file.

_LOCALE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$")

_PRODUCED_AT_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _validate_produced_at_utc(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(
            "produced_at_utc must be an ISO-8601 UTC string with microsecond precision and Z suffix"
        )
    if not _PRODUCED_AT_UTC_RE.fullmatch(value):
        raise ValueError(
            "produced_at_utc must be an ISO-8601 UTC string with microsecond precision and Z suffix"
        )
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValueError(
            "produced_at_utc must be a valid UTC timestamp with microsecond precision"
        ) from exc
    return value


def _canonicalize_locale_tag(locale: str | None) -> str | None:
    if locale is None:
        return None
    tag = locale.strip()
    if not tag:
        return None
    if not _LOCALE_TAG_RE.fullmatch(tag):
        return None

    parts = tag.split("-")
    if any(part == "" for part in parts):
        return None

    language = parts[0].lower()
    canonical_parts: list[str] = [language]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            canonical_parts.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            canonical_parts.append(part.title())
        else:
            canonical_parts.append(part.lower())
    return "-".join(canonical_parts)


def _resolve_locale_tag(locale: str | None) -> str:
    from ai.common.config import cfg

    canonical = _canonicalize_locale_tag(locale)
    if canonical is None:
        return cfg.nlp_default_locale

    chain = [
        normalized
        for normalized in (
            _canonicalize_locale_tag(entry) for entry in cfg.nlp_locale_fallback_chain
        )
        if normalized is not None
    ]
    if canonical in chain:
        return canonical

    language = canonical.split("-")[0]
    for entry in chain:
        if entry.split("-")[0] == language:
            return entry

    return cfg.nlp_default_locale


def _resolve_template_name(template_name: str, locale: "str | None" = None) -> str:
    """Resolve template name to locale-keyed path per §10.17.
    
    Parameters
    ----------
    template_name:
        Either full path (e.g., "predict.match_outcome.tr.j2") or intent-only
        (e.g., "predict.match_outcome").
    locale:
        Override locale (e.g., from Accept-Language). When None, uses
        ``cfg.nlp_default_locale``.
    
    Returns
    -------
    str
        Full template path with locale: "<intent>.<locale>.j2"
    
    Examples
    --------
    >>> _resolve_template_name("predict.match_outcome")
    "predict.match_outcome.tr-TR.j2"  # assuming cfg.nlp_default_locale="tr-TR"
    >>> _resolve_template_name("predict.match_outcome.tr.j2")
    "predict.match_outcome.tr.j2"  # already resolved, returned as-is
    >>> _resolve_template_name("predict.match_outcome", locale="en-GB")
    "predict.match_outcome.en-GB.j2"
    """
    # If already a full path with extension, return as-is for backward compat
    if template_name.endswith(".j2"):
        return template_name

    locale = _resolve_locale_tag(locale)
    return f"{template_name}.{locale}.j2"


_EMOJI_STRIP_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U0001F1E6-\U0001F1FF"
    "\uFE0F"
    "\u200D"
    "]"
)


def _strip_emoji(text: str) -> str:
    """Remove emoji-related codepoints from rendered answer text."""
    return _EMOJI_STRIP_RE.sub("", text)


def _normalize_screen_reader_answer(text: str) -> str:
    """Normalize rendered answer text for screen-reader-friendly output."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"%\s*(\d+)", r"yüzde \1", text)
    text = text.replace("✓", " evet ").replace("✗", " hayır ").replace("▶", " ")
    result: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if category in {"So", "Cf"} or category.startswith("M"):
            continue
        result.append(ch)
    normalized = "".join(result)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


def _sanitize_markdown_safe_answer(text: str) -> str:
    """Escape inline HTML in markdown_safe rendered output."""
    # Markdown safe output may include literal angle brackets as text,
    # but inline HTML tags are not permitted in the output. Escaping
    # the rendered string preserves the original content safely.
    return html.escape(text)

# ---------------------------------------------------------------------------
# Citation block contract (§10.7 binding)
# ---------------------------------------------------------------------------
# Every ``predict.*`` template ends with this line, followed by a structured
# citation block.  The delimiter separates humanizer-rephrasable prose from
# the invariant citation so the proofreader (§10.9) can sha256-verify it
# byte-for-byte.
CITATION_DELIMITER: str = "\n---\n"

# ---------------------------------------------------------------------------
# Degraded-mode disclaimer contract (§10.7 binding)
# ---------------------------------------------------------------------------
# When ``predict.approved.v1{degraded:true}`` the rendered body contains an
# operator-vetted Turkish disclaimer beginning with this prefix.  The humanizer
# (§10.8) MUST NOT rephrase this line; callers use :func:`strip_degraded_for_humanizer`
# before passing text to the LLM and :func:`reinsert_degraded_disclaimer` after.
DEGRADED_DISCLAIMER_PREFIX: str = "Tahmin sınırlı veriyle üretildi:"
_DEFAULT_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"
_INTENT_ENUM_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "swarm"
    / "sdk"
    / "schemas"
    / "_intent_enum.json"
)


def _load_closed_intent_enum() -> list[str]:
    """Load the closed intent enum used by template warm-up."""
    data = json.loads(_INTENT_ENUM_PATH.read_text(encoding="utf-8"))
    enum_values = data.get("enum", [])
    if not isinstance(enum_values, list):
        raise ValueError("invalid _intent_enum.json: enum must be a list")
    intents = [str(intent) for intent in enum_values]
    if not intents:
        raise ValueError("closed intent enum is empty")
    return intents


def _warm_fixture_context() -> dict[str, Any]:
    """Return a deterministic slot fixture used for Jinja warm-up renders."""
    return {
        "league_name": "Süper Lig",
        "season": "2025/26",
        "home_team": "Galatasaray",
        "away_team": "Fenerbahçe",
        "kickoff_utc": "2026-05-31T18:00:00Z",
        "venue": "RAMS Park",
        "matchday": 34,
        "h2h_rows": [
            {
                "date": "2026-04-10",
                "home": "Galatasaray",
                "home_goals": 2,
                "away_goals": 1,
                "away": "Fenerbahçe",
            }
        ],
        "player_name": "Mauro Icardi",
        "probability": 0.67,
        "risk_label": "orta",
        "degraded": False,
        "degraded_reason": "",
        "prediction_id": "warm-prediction-id",
        "produced_at_utc": "2026-05-31T18:00:00Z",
        "model_versions": ["predictor-v1@1.0.0"],
        "calibration_version": "cal-v1",
        "standings_rows": [
            {"team": "Galatasaray", "points": 90, "wins": 28, "draws": 6, "losses": 1}
        ],
        "suggestions": ["Galatasaray - Fenerbahçe tahmini"],
        "btts_label": "Evet",
        "citation_block": "[tahmin:warm-prediction-id]",
        "handicap_line": "-0.5",
        "outcome_label": "Ev sahibi",
        "threshold": "2.5",
        "direction_label": "Üst",
        "score_rows": [{"home_goals": 2, "away_goals": 1, "probability_pct": "34"}],
        "fixtures": [{"home": "Galatasaray", "away": "Fenerbahçe", "kickoff_utc": "2026-05-31T18:00:00Z"}],
        "collected_count": 1,
        "total_count": 1,
        "polarity": "affirm",
    }


def warm_closed_intent_templates(
    *,
    env: "jinja2.Environment | None" = None,
    intents: "list[str] | None" = None,
    context: "dict[str, Any] | None" = None,
) -> list[str]:
    """Render every closed-enum intent template once to warm bytecode cache.

    Returns the list of warmed template filenames.
    """
    if env is None:
        env = build_environment()
    warm_intents = intents or _load_closed_intent_enum()
    warm_context = context or _warm_fixture_context()

    warmed_templates: list[str] = []
    for intent in sorted(warm_intents):
        template_name = f"{intent}.tr.j2"
        template = env.get_template(template_name)
        template.render(**warm_context)
        warmed_templates.append(template_name)
    return warmed_templates


def build_environment(
    template_dir: "str | pathlib.Path | None" = None,
    confidence_bands: "list | None" = None,
    *,
    user_text_for_guard: "str | None" = None,
) -> jinja2.Environment:
    """Build and return a configured Jinja2 Environment for NLP templates.

    Parameters
    ----------
    template_dir:
        Path to the directory containing ``*.tr.j2`` templates.  Defaults to
        the ``ai/nlp/templates/`` folder next to this file.
    confidence_bands:
        List of ``[lower_inclusive, upper_exclusive, label]`` triples for
        :func:`nlp.jinja_filters_tr.confidence_band`.  When *None* the default
        §10.7 three-band table is used.  Passed to the filter via a closure so
        templates can call ``{{ prob | confidence_band }}`` without knowing the
        threshold values.
    user_text_for_guard:
        Original user input text for the §10.21.6 runtime guard. When provided,
        the finalize callable checks that no rendered slot contains a substring
        from this text (length ≥ cfg.nlp_template_finalize_min_user_text_len).
        When None, the guard is disabled (tests/non-production).
    """
    # Import lazily to avoid circular dependency at module load
    from ai.common.config import cfg
    
    tdir = pathlib.Path(template_dir) if template_dir is not None else _DEFAULT_TEMPLATE_DIR
    loader = jinja2.FileSystemLoader(str(tdir), encoding="utf-8")
    
    # §10.21.2 bytecode cache — ensure cache directory exists
    bcc_dir = pathlib.Path(cfg.nlp_jinja_bcc_dir)
    bcc_dir.mkdir(parents=True, exist_ok=True)
    bcc = jinja2.bccache.FileSystemBytecodeCache(
        str(bcc_dir),
        pattern="__nlp_%s.cache"
    )
    
    # §10.21.6 finalize callable: runtime guard that blocks render if any
    # slot contains the original user input.
    def _finalize_guard(value: Any) -> Any:
        """Check rendered value against original user text."""
        if user_text_for_guard is None:
            return value
        if not isinstance(value, str):
            return value
        min_len = cfg.nlp_template_finalize_min_user_text_len
        if len(user_text_for_guard) < min_len:
            return value
        if len(value) < min_len:
            return value
        # Check if this rendered value contains a substring from the original
        # user text (case-insensitive to catch variants), or if the rendered
        # value itself is a substring from the user text. Use casefold() for
        # proper Turkish İ/I handling.
        user_folded = user_text_for_guard.casefold()
        value_folded = value.casefold()
        # Case 1: rendered value contains the whole user text
        if user_folded in value_folded:
            raise RawUserTextInTemplateError(
                matched_substring=value[:100],
                original_text=user_text_for_guard[:100],
            )
        # Case 2: rendered value is a substring from user text (≥ min_len)
        if value_folded in user_folded:
            raise RawUserTextInTemplateError(
                matched_substring=value[:100],
                original_text=user_text_for_guard[:100],
            )
        return value
    
    env = jinja2.Environment(
        loader=loader,
        autoescape=False,
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        bytecode_cache=bcc,
        auto_reload=False,  # §10.21.2: no runtime recompilation
        finalize=_finalize_guard,
    )
    # Register base filters (excludes confidence_band \u2014 bound separately below).
    env.filters.update({k: v for k, v in sorted(FILTERS.items()) if k != "confidence_band"})
    # Bind confidence_bands into a closure so the template may call either:
    #   {{ prob | confidence_band }}   (filter syntax)
    #   {{ confidence_band(prob) }}    (global-function syntax, used in current templates)
    _bands = confidence_bands

    def _band_filter(prob: float) -> str:
        return confidence_band(prob, _bands)

    env.filters["confidence_band"] = _band_filter
    # Expose confidence_band and kickoff_time as Jinja2 globals so templates can
    # call them as functions (current template style: {{ confidence_band(prob) }},
    # {{ kickoff_time(dt) }}).
    env.globals["confidence_band"] = _band_filter
    env.globals["kickoff_time"] = kickoff_time
    return env


_ALLOWED_ANSWER_FORMATS = frozenset(
    {
        "plain",
        "markdown_safe",
        "screen_reader",
        "whatsapp_4096",
        "sms_160",
        "tts_neutral",
    }
)


def render(
    template_name: str,
    context: "dict[str, Any]",
    *,
    env: "jinja2.Environment | None" = None,
    fallback_env: "jinja2.Environment | None" = None,
    answer_format: str = "plain",
    tenant_id: str | None = None,
    locale: str | None = None,
) -> str:
    """Render *template_name* with *context*, falling back to meta.unsupported.

    Parameters
    ----------
    template_name:
        Bare template name, e.g. ``"predict.match_outcome.tr.j2"``.
    context:
        Slot values available to the template.
    env:
        Pre-built :class:`jinja2.Environment`.  When *None* one is built from
        defaults (``build_environment()``).
    fallback_env:
        Environment used for the ``meta.unsupported`` fallback.  Defaults to
        *env*.
    answer_format:
        Output format for the rendered answer. ``plain`` and
        ``markdown_safe`` preserve rendered text; ``screen_reader`` strips
        emoji and decorative characters for assistive technology.

    Returns
    -------
    str
        Rendered answer text.  This function never raises:
        ``jinja2.UndefinedError`` from a missing slot is caught and the
        ``meta.unsupported.tr.j2`` template is rendered with the error message
        as a ``suggestions`` list.  If even that fails, a hard-coded Turkish
        apology is returned.
    """
    if env is None:
        env = build_environment()
    if fallback_env is None:
        fallback_env = env
    from ai.common.config import cfg

    if answer_format not in _ALLOWED_ANSWER_FORMATS:
        raise ValueError(f"unsupported answer_format: {answer_format!r}")
    if not isinstance(cfg.nlp_answer_format_enabled, dict) or not cfg.nlp_answer_format_enabled.get(answer_format, False):
        template_name = "meta.format_unsupported.tr.j2"
    # For predict templates, synthesize the canonical citation block from the
    # closed-schema citation dict when callers provide raw fields.
    render_context = dict(context)
    if template_name.startswith("predict.") and "citation_block" not in render_context:
        required = (
            "prediction_id",
            "produced_at_utc",
            "model_versions",
            "calibration_version",
        )
        if all(k in render_context for k in required):
            citation_data = {
                "prediction_id": render_context["prediction_id"],
                "produced_at_utc": render_context["produced_at_utc"],
                "model_versions": render_context["model_versions"],
                "calibration_version": render_context["calibration_version"],
            }
            if "degraded_reason" in render_context and render_context["degraded_reason"]:
                citation_data["degraded_reason"] = render_context["degraded_reason"]
            render_context["citation_block"] = render_citation_block(citation_data)

    try:
        tmpl = env.get_template(template_name)
        rendered = tmpl.render(**render_context)

        from ai.common.config import cfg

        if answer_format == "screen_reader":
            rendered = _normalize_screen_reader_answer(rendered)
        elif answer_format == "markdown_safe":
            rendered = _sanitize_markdown_safe_answer(rendered)
            if not cfg.nlp_answer_decorative_emoji_enabled:
                rendered = _strip_emoji(rendered)
        else:
            if not cfg.nlp_answer_decorative_emoji_enabled:
                rendered = _strip_emoji(rendered)

        if tenant_id is not None:
            from nlp.compliance.banlist import apply_banlist_overlay

            resolved_locale = _resolve_locale_tag(locale)
            rendered = apply_banlist_overlay(rendered, tenant_id=tenant_id, locale=resolved_locale)

        return rendered
    except jinja2.UndefinedError as exc:
        # Missing slot: route to meta.unsupported.
        unsupported_ctx: dict[str, Any] = {"suggestions": [str(exc)]}
        try:
            result = fallback_env.get_template("meta.unsupported.tr.j2").render(
                **unsupported_ctx
            )
            if answer_format == "screen_reader":
                return _normalize_screen_reader_answer(result)
            if answer_format == "markdown_safe":
                return _sanitize_markdown_safe_answer(result)
            return result
        except Exception:  # noqa: BLE001 — absolute last resort
            return "\u00dczg\u00fcn\u00fcm, bu soruyu yan\u0131tlayam\u0131yorum."


# ---------------------------------------------------------------------------
# Citation block helpers (§10.7 binding)
# ---------------------------------------------------------------------------

def extract_citation_block(rendered_text: str) -> "tuple[str, str | None]":
    """Split *rendered_text* into *(body, citation_block)*.

    The citation block is the content after the first :data:`CITATION_DELIMITER`.
    Returns ``(rendered_text, None)`` if the delimiter is absent (non-predict
    templates such as ``meta.*`` and ``data.*`` carry no citation).

    The extracted *citation_block* includes any trailing newline exactly as the
    template emitted it — no stripping — so that ``citation_sha256`` is stable.
    """
    parts = rendered_text.split(CITATION_DELIMITER, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return rendered_text, None


def citation_sha256(citation_block: str) -> str:
    """Return the SHA-256 hex digest (64 chars) of *citation_block* (UTF-8).

    Used by the proofreader (§10.9) to verify the citation block has not been
    modified between dispatch and publication.  Inputs are the raw string from
    :func:`extract_citation_block`; no stripping or normalisation is applied so
    the digest is byte-for-byte deterministic.
    """
    return hashlib.sha256(citation_block.encode("utf-8")).hexdigest()


def render_with_citation(
    template_name: str,
    context: "dict[str, Any]",
    *,
    locale: "str | None" = None,
    env: "jinja2.Environment | None" = None,
    fallback_env: "jinja2.Environment | None" = None,
    answer_format: str = "plain",
    tenant_id: str | None = None,
) -> "tuple[str, str | None]":
    """Render *template_name* and return ``(answer_text, citation_sha256_or_None)``.

    For ``predict.*`` templates that contain a :data:`CITATION_DELIMITER` the
    second element is the SHA-256 hex digest of the citation block — the value
    the dispatcher stamps and the proofreader verifies byte-for-byte (§10.9
    gate 1).

    For non-predict templates (``meta.*``, ``data.*``, ``summary.*``) the
    citation block is absent and the second element is ``None``.

    Parameters
    ----------
    template_name, context, locale, env, fallback_env, answer_format:
        Forwarded verbatim to :func:`render`.
    """
    _ = locale  # Reserved for future locale-resolved rendering path.
    text = render(
        template_name,
        context,
        env=env,
        fallback_env=fallback_env,
        answer_format=answer_format,
        tenant_id=tenant_id,
        locale=locale,
    )
    _, citation = extract_citation_block(text)
    if citation is None:
        return text, None
    return text, citation_sha256(citation)


# ---------------------------------------------------------------------------
# Degraded-mode humanizer bypass (§10.7 binding)
# ---------------------------------------------------------------------------

def strip_degraded_for_humanizer(text: str) -> "tuple[str, str | None]":
    """Remove the degraded disclaimer line from *text* before humanizer rephrasing.

    The humanizer (§10.8) must NOT rephrase the operator-vetted disclaimer
    (§10.7 binding: "humanizer is bypassed for the disclaimer line").  This
    helper:

    1. Splits *text* on :data:`CITATION_DELIMITER` to isolate the body prose.
    2. Scans the body prose for any line whose stripped form starts with
       :data:`DEGRADED_DISCLAIMER_PREFIX` and removes it.
    3. Collapses any run of 3+ consecutive newlines left by the removed block
       down to two (preserves paragraph spacing without introducing gaps).
    4. Returns ``(text_safe_for_humanizer, disclaimer_line_or_None)``.

    If no disclaimer is present (``degraded=False`` renders, or non-predict
    templates) the second element is ``None`` and *text* is returned unchanged.
    """
    parts = text.split(CITATION_DELIMITER, 1)
    body = parts[0]
    has_citation = len(parts) == 2

    disclaimer: "str | None" = None
    new_lines = []
    for line in body.splitlines(keepends=True):
        if line.strip().startswith(DEGRADED_DISCLAIMER_PREFIX):
            disclaimer = line.rstrip("\n")
        else:
            new_lines.append(line)

    if disclaimer is None:
        return text, None

    cleaned_body = "".join(new_lines)
    # Collapse any 3+ consecutive newlines to at most 2 (blank-line boundary).
    cleaned_body = re.sub(r"\n{3,}", "\n\n", cleaned_body)

    if has_citation:
        return cleaned_body + CITATION_DELIMITER + parts[1], disclaimer
    return cleaned_body, disclaimer


def reinsert_degraded_disclaimer(text: str, disclaimer: "str | None") -> str:
    """Re-insert *disclaimer* into *text* immediately before the citation block.

    Called after the humanizer has rephrased the body prose — which had the
    disclaimer stripped by :func:`strip_degraded_for_humanizer`.  The
    disclaimer is placed on its own line immediately before
    :data:`CITATION_DELIMITER` so the final answer reads::

        <humanized prose>
        Tahmin sınırlı veriyle üretildi: <reason>
        ---
        [citation block]

    If *disclaimer* is ``None`` (non-degraded path) *text* is returned
    unchanged.
    """
    if disclaimer is None:
        return text

    if CITATION_DELIMITER in text:
        head, tail = text.split(CITATION_DELIMITER, 1)
        # Ensure exactly one blank line separates prose from disclaimer, and
        # disclaimer ends with a newline before the delimiter.
        return head.rstrip("\n") + "\n" + disclaimer + CITATION_DELIMITER + tail

    # Non-predict template or no citation: append disclaimer at end.
    return text.rstrip("\n") + "\n" + disclaimer + "\n"


# ---------------------------------------------------------------------------
# §10.21.6 Citation block canonical rendering
# ---------------------------------------------------------------------------
def render_citation_block(citation_data: dict[str, Any]) -> str:
    """Render citation block in normalized canonical form (§10.21.6).
    
    Parameters
    ----------
    citation_data:
        Closed-schema dict with ONLY these keys (extra keys raise ValueError):
        - prediction_id: str
        - produced_at_utc: str
        - model_versions: list[str]
        - calibration_version: int
        - degraded_reason: str (optional)
    
    Returns
    -------
    str
        Citation block in canonical form: sorted keys, fixed whitespace,
        byte-stable for sha256 round-trip per §10.9.
    
    Raises
    ------
    ValueError
        When citation_data contains keys not in the closed schema.
    KeyError
        When required keys are missing.
    
    Notes
    -----
    This function enforces the §10.21.6 contract: citation block renders from
    a single closed-schema dict; no other slots permitted. AST tests verify
    that templates use only this helper (or inline only these fields).
    
    The canonical form is:
        [tahmin:<prediction_id> | üretim:<produced_at_utc> | kalibrasyon:<calibration_version> | modeller:<models>]
    
    When degraded_reason is present, an additional line is added:
        [sebep:<degraded_reason>]
    
    Fields are always emitted in the same order regardless of dict iteration
    order (per §10.21.1 determinism).
    """
    # Closed schema: ONLY these keys are permitted
    ALLOWED_KEYS = frozenset({
        "prediction_id",
        "produced_at_utc",
        "model_versions",
        "calibration_version",
        "degraded_reason",
    })
    REQUIRED_KEYS = frozenset({
        "prediction_id",
        "produced_at_utc",
        "model_versions",
        "calibration_version",
    })
    
    # Validate schema compliance
    provided_keys = frozenset(citation_data.keys())
    extra_keys = provided_keys - ALLOWED_KEYS
    if extra_keys:
        raise ValueError(
            f"Citation block received disallowed keys: {sorted(extra_keys)}. "
            f"Only {sorted(ALLOWED_KEYS)} are permitted per §10.21.6."
        )
    
    missing_keys = REQUIRED_KEYS - provided_keys
    if missing_keys:
        raise KeyError(
            f"Citation block missing required keys: {sorted(missing_keys)}. "
            f"Required: {sorted(REQUIRED_KEYS)}."
        )
    
    # Extract fields (deterministic order, not dict iteration order)
    prediction_id = citation_data["prediction_id"]
    produced_at_utc = citation_data["produced_at_utc"]
    _validate_produced_at_utc(produced_at_utc)
    model_versions = citation_data["model_versions"]
    calibration_version = citation_data["calibration_version"]
    degraded_reason = citation_data.get("degraded_reason", None)
    
    # Normalize model_versions to a deterministic string (sorted)
    if not isinstance(model_versions, list):
        raise TypeError(
            f"model_versions must be list[str], got {type(model_versions).__name__}"
        )
    models_str = ", ".join(sorted(str(m) for m in model_versions))
    
    # Build canonical form (fixed order, fixed whitespace)
    lines = []
    lines.append(
        f"[tahmin:{prediction_id} | üretim:{produced_at_utc} | "
        f"kalibrasyon:{calibration_version} | modeller:{models_str}]"
    )
    
    if degraded_reason:
        lines.append(f"[sebep:{degraded_reason}]")
    
    # Join with newline, ensure trailing newline for byte-stability
    return "\n".join(lines) + "\n"
