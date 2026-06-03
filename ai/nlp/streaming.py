from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from common.config import Config
from common.security.patterns import detect_pii
from nlp.render import CITATION_DELIMITER, extract_citation_block


@dataclass(frozen=True)
class GuardedStreamingPlan:
    skeleton: str
    citation_block: str | None
    skeleton_chunks: list[str]
    final_answer: str
    humanizer_used: bool
    canceled: bool
    write_timed_out: bool
    chunk_blocked_reason: str | None = None


def _chunk_text(text: str, chunk_chars: int) -> list[str]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be > 0")

    chunks: list[str] = []
    cursor = 0
    length = len(text)

    while cursor < length:
        end = min(length, cursor + chunk_chars)
        if end < length and text[end] != " ":
            split_at = text.rfind(" ", cursor, end)
            if split_at > cursor:
                end = split_at
        if end == cursor:
            end = min(length, cursor + chunk_chars)
        chunk = text[cursor:end]
        chunks.append(chunk)
        cursor = end
        if cursor < length and text[cursor] == " ":
            cursor += 1

    return chunks


def build_guarded_streaming_plan(
    answer_text: str,
    *,
    cfg: Config,
    humanizer: Callable[[str, Config], str],
    cancel_token: Callable[[], bool] | None = None,
    write_chunk: Callable[[str], None] | None = None,
    chunk_proofread_fn: Callable[[str], str | None] | None = None,
) -> GuardedStreamingPlan:
    body, citation_block = extract_citation_block(answer_text)
    skeleton = body
    chunk_chars = cfg.nlp_streaming_proofread_chunk_chars
    skeleton_chunks = _chunk_text(skeleton, chunk_chars)

    if cfg.nlp_answer_streaming != "guarded":
        return GuardedStreamingPlan(
            skeleton=skeleton,
            citation_block=citation_block,
            skeleton_chunks=[answer_text],
            final_answer=answer_text,
            humanizer_used=False,
            canceled=False,
            write_timed_out=False,
        )

    def _is_cancelled() -> bool:
        return cancel_token() if cancel_token is not None else False

    if _is_cancelled():
        final_answer = skeleton + (CITATION_DELIMITER + citation_block if citation_block else "")
        return GuardedStreamingPlan(
            skeleton=skeleton,
            citation_block=citation_block,
            skeleton_chunks=skeleton_chunks,
            final_answer=final_answer,
            humanizer_used=False,
            canceled=True,
            write_timed_out=False,
        )

    if write_chunk is not None:
        for chunk in skeleton_chunks:
            if chunk_proofread_fn is not None:
                blocked_reason = chunk_proofread_fn(chunk)
                if blocked_reason is not None:
                    final_answer = skeleton + (CITATION_DELIMITER + citation_block if citation_block else "")
                    return GuardedStreamingPlan(
                        skeleton=skeleton,
                        citation_block=citation_block,
                        skeleton_chunks=skeleton_chunks,
                        final_answer=final_answer,
                        humanizer_used=False,
                        canceled=False,
                        write_timed_out=False,
                        chunk_blocked_reason=blocked_reason,
                    )
            try:
                write_chunk(chunk)
            except TimeoutError:
                final_answer = skeleton + (CITATION_DELIMITER + citation_block if citation_block else "")
                return GuardedStreamingPlan(
                    skeleton=skeleton,
                    citation_block=citation_block,
                    skeleton_chunks=skeleton_chunks,
                    final_answer=final_answer,
                    humanizer_used=False,
                    canceled=False,
                    write_timed_out=True,
                )
            if _is_cancelled():
                final_answer = skeleton + (CITATION_DELIMITER + citation_block if citation_block else "")
                return GuardedStreamingPlan(
                    skeleton=skeleton,
                    citation_block=citation_block,
                    skeleton_chunks=skeleton_chunks,
                    final_answer=final_answer,
                    humanizer_used=False,
                    canceled=True,
                    write_timed_out=False,
                )

    final_body = humanizer(skeleton, cfg)
    final_answer = final_body + (CITATION_DELIMITER + citation_block if citation_block else "")

    return GuardedStreamingPlan(
        skeleton=skeleton,
        citation_block=citation_block,
        skeleton_chunks=skeleton_chunks,
        final_answer=final_answer,
        humanizer_used=True,
        canceled=False,
        write_timed_out=False,
    )
