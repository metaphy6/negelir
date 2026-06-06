from swarm.bootstrap import build_agents
from swarm.agents.topics import (
    DATA_REQUEST_V1,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    NLP_GOSSIP_V1,
    NLP_PROBER_V1,
    NLP_SHADOW_V1,
    PREDICT_REQUEST_V1,
    QA_ANSWER_V1,
    QA_CONTEXT_EXTENSION_V1,
    QA_CONTEXT_V1,
    QA_INTENT_V1,
)


def test_nlp_boundary_discipline_outbound_set() -> None:
    """§10.0 boundary: NLP outbound topics must be exactly the approved set."""
    expected = {
        QA_INTENT_V1,
        QA_ANSWER_V1,
        QA_CONTEXT_V1,
        QA_CONTEXT_EXTENSION_V1,
        NLP_EVENT_V1,
        NLP_ALERT_V1,
        NLP_GOSSIP_V1,
        NLP_SHADOW_V1,
        NLP_PROBER_V1,
        PREDICT_REQUEST_V1,
        DATA_REQUEST_V1,
    }

    actual = set()
    for agent in build_agents():
        if not str(getattr(agent, "name", "")).startswith("nlp."):
            continue
        actual.update(getattr(agent, "publishes", ()))

    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        "NLP outbound topic set must equal the approved Phase 10 wire set. "
        f"Missing: {sorted(str(t) for t in missing)}; "
        f"Unexpected: {sorted(str(t) for t in extra)}."
    )
