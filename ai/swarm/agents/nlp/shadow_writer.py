from __future__ import annotations

from swarm.agents.topics import NLP_SHADOW_V1, QA_INTENT_V1
from swarm.sdk.types import Message


class NlpShadowWriter:
    name = "nlp.shadow_writer.v1"
    subscribes = [QA_INTENT_V1]
    publishes = [NLP_SHADOW_V1]

    def handle(self, msg: Message) -> list[Message]:
        payload = msg.payload
        preview = False
        request_metadata = payload.get("request_metadata")
        if isinstance(request_metadata, dict):
            preview = bool(request_metadata.get("preview"))
        if preview:
            return []
        return [
            Message.new(
                topic=NLP_SHADOW_V1,
                payload={**payload},
                producer=self.name,
            )
        ]
