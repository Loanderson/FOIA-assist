"""Every model call goes through here. The gateway checks the handling level
of everything in the prompt against the endpoint's authorization, refuses
anything over the line, and writes an audit record either way. Audit records
hold document IDs and a prompt hash, never the content itself."""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import policy
from .llm import ChatClient

AUDIT_PATH = Path(__file__).resolve().parent.parent / "audit" / "audit.jsonl"


class AuditLog:
    def __init__(self, path: str | Path | None = AUDIT_PATH):
        self.path = Path(path) if path else None
        self.records: list[dict] = []

    def write(self, **record) -> dict:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
        self.records.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        return record


class Gateway:
    def __init__(self, endpoint: dict, audit: AuditLog, client=None):
        self.endpoint = endpoint
        self.audit = audit
        self.client = client or (ChatClient(endpoint) if endpoint["kind"] != "offline" else None)

    @property
    def offline(self) -> bool:
        return self.endpoint["kind"] == "offline"

    def permits(self, level: str) -> bool:
        return policy.allowed(level, self.endpoint["authorized_level"])

    def ask(self, request_id: str, purpose: str, system: str, user: str, schema: dict,
            sources: list[tuple[str, str]]) -> dict:
        """sources: (source_id, handling_level) for everything in the prompt."""
        levels = [lvl for _, lvl in sources]
        base = {"request_id": request_id, "purpose": purpose, "endpoint": self.endpoint["name"],
                "endpoint_level": self.endpoint["authorized_level"],
                "content_level": policy.max_level(levels), "sources": [s for s, _ in sources],
                "prompt_sha256": hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:16]}
        try:
            policy.check(levels, self.endpoint)
        except policy.PolicyViolation as e:
            self.audit.write(event="model_call_blocked", reason=str(e), **base)
            raise
        if self.offline:
            raise RuntimeError("offline endpoint has no model; caller should use rules")
        start = time.perf_counter()
        try:
            result, usage = self.client.complete_json(system, user, schema, purpose)
        except Exception as e:
            self.audit.write(event="model_call_failed", error=str(e), **base)
            raise
        self.audit.write(event="model_call", latency_ms=int((time.perf_counter() - start) * 1000),
                         usage=usage, **base)
        return result
