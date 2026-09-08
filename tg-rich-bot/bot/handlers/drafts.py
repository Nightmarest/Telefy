"""In-memory draft store.

Keyed by a short opaque token that we round-trip through
inline-button callback_data (max 64 bytes). When the user hits
Publish/Redo/Drop we look up the original RichMessage payload here.

Drafts auto-expire after `ttl` seconds so the dict doesn't grow without
bound across a long-running session.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Draft:
    token: str
    user_id: int
    payload: dict[str, Any]
    preview_chat_id: int
    preview_message_id: int
    created_at: float = field(default_factory=time.monotonic)


class DraftStore:
    def __init__(self, ttl: float = 24 * 3600) -> None:
        self._ttl = ttl
        self._by_token: dict[str, Draft] = {}

    def create(
        self,
        user_id: int,
        payload: dict[str, Any],
        preview_chat_id: int,
        preview_message_id: int,
    ) -> Draft:
        self._gc()
        token = secrets.token_urlsafe(8)  # 11 chars, well within 64-byte cap
        d = Draft(
            token=token, user_id=user_id, payload=payload,
            preview_chat_id=preview_chat_id,
            preview_message_id=preview_message_id,
        )
        self._by_token[token] = d
        return d

    def get(self, token: str) -> Draft | None:
        self._gc()
        return self._by_token.get(token)

    def drop(self, token: str) -> Draft | None:
        return self._by_token.pop(token, None)

    def _gc(self) -> None:
        now = time.monotonic()
        stale = [t for t, d in self._by_token.items() if now - d.created_at > self._ttl]
        for t in stale:
            self._by_token.pop(t, None)
