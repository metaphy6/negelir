"""Feed contract and encoding utilities."""

from .canonical import encode, idempotency_key
from .reader import FeedCursor, FeedReader

__all__ = ["encode", "idempotency_key", "FeedReader", "FeedCursor"]


# Re-export dedup for convenience (Phase 16.4, bullet 3)
def dedup(stream, key=("stable_id", "captured_at"), lru_size=100_000):
    """Deduplicate at-least-once records from a stream (Phase 16.4, bullet 3).
    
    Convenience wrapper around FeedReader.dedup() for use with stream() results.
    
    Args:
        stream: Iterator yielding (record, cursor) tuples from FeedReader.stream()
        key: Tuple of field names to use for dedup key
        lru_size: Max size of the LRU cache
        
    Yields:
        Tuples of (record, cursor, is_duplicate)
    """
    return FeedReader.dedup(stream, key=key, lru_size=lru_size)
