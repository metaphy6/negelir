"""
Negelir P2P — Persistent node identity.
Phase 3: Survives container restarts so peer reputation is maintained.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from node.peer import get_p2p_logger

log = get_p2p_logger("node.identity")

DEFAULT_IDENTITY_PATH = Path("~/.negelir/identity.json").expanduser()


def load_or_create_identity(path: Path | None = None) -> dict:
    """
    Load node_id from disk. Create if first run.
    Ensures peer reputation survives across restarts.

    Returns:
        {"node_id": "uuid-string", "created_at": "iso-timestamp"}
    """
    identity_path = path or DEFAULT_IDENTITY_PATH

    if identity_path.exists():
        try:
            data = json.loads(identity_path.read_text(encoding="utf-8"))
            if "node_id" in data:
                log.info(f"Loaded identity: {data['node_id'][:12]}...")
                return data
        except (json.JSONDecodeError, OSError) as exc:
            log.warning(f"Corrupt identity file, regenerating: {exc}")

    identity = {
        "node_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")
    log.info(f"Created new identity: {identity['node_id'][:12]}...")
    return identity
