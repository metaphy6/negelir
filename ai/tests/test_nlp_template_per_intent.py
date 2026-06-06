"""Phase 10 §10.7 + §10.15 — Template layout and hallucination guard.

§10.7: Coverage gate: every intent in the closed enum must have exactly one
Jinja2 template at ai/nlp/templates/<intent>.tr.j2.

§10.15: Hallucination guard: templates must reference only canonical entities
from the resolved entity list OR static template-baked phrases. No arbitrary
free-text interpolation allowed (make nlp.template-lint AST-asserts this).
"""
import json
import pathlib

ENUM_FILE = pathlib.Path("ai/swarm/sdk/schemas/_intent_enum.json")
TEMPLATES_DIR = pathlib.Path("ai/nlp/templates")


def _load_intents() -> list:
    data = json.loads(ENUM_FILE.read_text(encoding="utf-8"))
    return data["enum"]


def test_template_dir_exists():
    assert TEMPLATES_DIR.is_dir(), (
        f"{TEMPLATES_DIR} does not exist; create it with one .tr.j2 per intent"
    )


def test_template_per_intent():
    """Every intent in the closed enum must have a corresponding .tr.j2 file."""
    intents = _load_intents()
    assert intents, "Intent enum is empty"

    missing = []
    for intent in intents:
        expected = TEMPLATES_DIR / f"{intent}.tr.j2"
        if not expected.is_file():
            missing.append(str(expected))

    assert not missing, (
        f"Missing template(s) for {len(missing)} intent(s):\n"
        + "\n".join(f"  {m}" for m in sorted(missing))
    )


def test_no_extra_templates():
    """Adversarial: no .tr.j2 file outside the closed enum (keeps templates tidy)."""
    intents = set(_load_intents())
    allowed = {f"{i}.tr.j2" for i in intents}

    extras = [
        str(f)
        for f in TEMPLATES_DIR.glob("*.tr.j2")
        if f.name not in allowed
    ]
    assert not extras, (
        f"Template file(s) not in closed enum:\n"
        + "\n".join(f"  {e}" for e in sorted(extras))
    )


def test_templates_are_non_empty():
    """Each template must have at least one non-whitespace character."""
    intents = _load_intents()
    empty = []
    for intent in intents:
        path = TEMPLATES_DIR / f"{intent}.tr.j2"
        if path.is_file() and not path.read_text(encoding="utf-8").strip():
            empty.append(intent)
    assert not empty, f"Empty template(s): {empty}"


def test_no_free_text_slots():
    """§10.15 Hallucination guard: AST-assert no {{ free_text }} or similar
    unstructured slots in any template.

    Forbidden patterns defined in xops/makefile/nlp.py::cmd_nlp_template_lint
    FORBIDDEN_SLOTS set. This test is the enforcement gate; make nlp.template-lint
    is the CI-friendly invocation of the same logic.
    """
    import jinja2
    from jinja2 import nodes

    # Same forbidden list as in xops/makefile/nlp.py::cmd_nlp_template_lint
    FORBIDDEN_SLOTS = {
        "free_text", "raw_input", "user_query", "unstructured",
        "arbitrary_text", "custom_message",
    }

    def extract_variables(node):
        """Recursively extract all Name nodes from a Jinja2 AST."""
        variables = set()
        if isinstance(node, nodes.Name):
            variables.add(node.name)
        for child in node.iter_child_nodes():
            variables.update(extract_variables(child))
        return variables

    failed = []
    for tpl_path in TEMPLATES_DIR.glob("*.tr.j2"):
        source = tpl_path.read_text(encoding="utf-8")
        try:
            env = jinja2.Environment()
            ast = env.parse(source)
            variables = extract_variables(ast)

            for var in variables:
                if var in FORBIDDEN_SLOTS:
                    failed.append((tpl_path.name, var))
        except jinja2.TemplateSyntaxError:
            # Syntax errors are covered by separate test; skip here
            pass

    assert not failed, (
        f"Forbidden unstructured slot(s) found in template(s):\n"
        + "\n".join(f"  {tpl}: {{ {var} }}" for tpl, var in sorted(failed))
        + "\n\n§10.15 Hallucination guard: templates must use only canonical "
        "entity slots or static phrases. No {{ free_text }} allowed."
    )


def test_templates_do_not_embed_disclosure_text():
    """§10.27.8: templates must not contain closed disclosure text verbatim."""
    import yaml

    disclosure_path = pathlib.Path("ai") / "nlp" / "compliance" / "disclosures.tr.yaml"
    disclosures = yaml.safe_load(disclosure_path.read_text(encoding="utf-8")) or {}
    disclosure_texts = [
        item["text"]
        for item in disclosures.get("disclosures", [])
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    ]

    failures: list[str] = []
    for tpl_path in TEMPLATES_DIR.glob("*.tr.j2"):
        source = tpl_path.read_text(encoding="utf-8")
        for disclosure_text in disclosure_texts:
            if disclosure_text and disclosure_text in source:
                failures.append(f"{tpl_path.name}: disclosure text found")

    assert not failures, (
        "Templates must not contain raw disclosure text; use the renderer instead:\n"
        + "\n".join(sorted(failures))
    )


def test_meta_adversarial_off_topic_handling():
    """§10.15 off-topic handling: meta.adversarial must return the exact
    spec-defined Turkish redirection.

    Fixed phrasing (no slots), humanizer bypassed (§10.8 meta.* intents list),
    proofreader still runs PII check (implicit via agent flow).
    """
    from nlp.render import build_environment

    env = build_environment()
    template = env.get_template("meta.adversarial.tr.j2")
    rendered = template.render().rstrip("\n")

    EXPECTED = "Bu konuda yardımcı olamıyorum; lütfen futbolla ilgili bir soru sorun."
    assert rendered == EXPECTED, (
        f"meta.adversarial template must produce exact spec text.\n"
        f"Expected: {EXPECTED!r}\n"
        f"Got:      {rendered!r}"
    )


def test_meta_intents_bypass_humanizer_documented():
    """§10.15: humanizer module must document that meta.* intents bypass
    the LLM rephrasing (fixed phrasing per template).
    """
    from nlp.humanizer import humanize

    doc = humanize.__doc__ or ""
    assert "§10.15" in doc, (
        "humanize() docstring must reference §10.15 for meta.* bypass list"
    )
    assert "meta.*" in doc or "meta.help" in doc or "meta.adversarial" in doc, (
        "humanize() docstring must list meta.* intents as humanizer-bypassed"
    )
    assert "fixed phrasing" in doc or "NOT be rephrased" in doc, (
        "humanize() docstring must document that meta.* use fixed phrasing"
    )
