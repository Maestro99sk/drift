"""Anthropic-backed dossier adapter.

Uses Haiku for cheap IP classification and Sonnet for dossier generation. The shared
system prompt is sent with cache_control so it amortises across many candidates per tick.
Opus is reserved for strategy on already-cleared items (caller's choice).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from drift.config import get_settings
from drift.dossier.base import DossierAdapter, DossierDraft, DossierInputs
from drift.dossier.prompts import (
    IP_CLASSIFIER_SYSTEM,
    SYSTEM_PROMPT,
    dossier_user_prompt,
)

log = logging.getLogger(__name__)


def _parse_json(text: str) -> dict:
    text = text.strip()
    # Defensive: strip code fences if the model wrapped them despite instructions.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return json.loads(text)


class AnthropicDossierAdapter(DossierAdapter):
    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            s = get_settings()
            if not s.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY missing")
            self._client = AsyncAnthropic(api_key=s.anthropic_api_key)
        return self._client

    async def generate(self, inputs: DossierInputs) -> DossierDraft:
        s = get_settings()
        client = self._get_client()
        user = dossier_user_prompt(json.dumps(asdict(inputs)))

        resp = await client.messages.create(
            model=s.llm_dossier_model,
            max_tokens=s.llm_max_tokens,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        try:
            data = _parse_json(text)
        except json.JSONDecodeError:
            log.warning("Dossier returned non-JSON; using empty draft")
            return DossierDraft(ad_angle="", copy="", projected_unit_economics={})
        return DossierDraft(
            ad_angle=data.get("ad_angle", ""),
            copy=data.get("copy", ""),
            projected_unit_economics=data.get("projected_unit_economics", {}),
        )

    async def classify_ip(self, text: str) -> tuple[bool | None, str | None]:
        s = get_settings()
        try:
            client = self._get_client()
        except RuntimeError:
            return None, "ANTHROPIC_API_KEY missing"
        resp = await client.messages.create(
            model=s.llm_filter_model,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": IP_CLASSIFIER_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": f"Product text:\n{text}"}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            data = _parse_json(raw)
        except json.JSONDecodeError:
            return None, "classifier returned non-JSON - fail closed"
        return bool(data.get("safe")), data.get("reason")
