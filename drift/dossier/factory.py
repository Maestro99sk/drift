from __future__ import annotations

from drift.config import get_settings
from drift.dossier.base import DossierAdapter


def get_dossier_adapter() -> DossierAdapter:
    s = get_settings()
    if s.is_mock("llm"):
        from drift.dossier.mock import MockDossierAdapter

        return MockDossierAdapter()
    from drift.dossier.anthropic import AnthropicDossierAdapter

    return AnthropicDossierAdapter()
