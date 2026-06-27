"""Mock dossier adapter - template-driven, deterministic, no network calls."""

from __future__ import annotations

from drift.dossier.base import DossierAdapter, DossierDraft, DossierInputs
from drift.scoring.ip_gate import ip_safe_keyword_check


def _project_economics(i: DossierInputs, assumed_cac: float = 8.0) -> dict:
    margin = max(0.0, i.suggested_sell_price - i.unit_cost)
    contribution = max(0.0, margin - assumed_cac)
    gm_frac = (margin / i.suggested_sell_price) if i.suggested_sell_price > 0 else 0.0
    return {
        "unit_cost": i.unit_cost,
        "sell_price": i.suggested_sell_price,
        "gross_margin": round(margin, 2),
        "assumed_cac": assumed_cac,
        "contribution_per_unit": round(contribution, 2),
        "roas_breakeven": round(1 / gm_frac, 2) if gm_frac > 0 else None,
    }


class MockDossierAdapter(DossierAdapter):
    async def generate(self, inputs: DossierInputs) -> DossierDraft:
        ad_angle = (
            f"For {inputs.category} buyers who want a no-nonsense {inputs.keyword} "
            f"shipped without fuss."
        )
        copy = (
            f"Meet our {inputs.keyword}. Designed for everyday {inputs.category} use, "
            f"built from durable materials, and shipped worldwide in roughly "
            f"{inputs.ship_days} days. No hype, no fluff - just the thing you actually "
            f"wanted, at a fair price."
        )
        return DossierDraft(
            ad_angle=ad_angle,
            copy=copy,
            projected_unit_economics=_project_economics(inputs),
        )

    async def classify_ip(self, text: str) -> tuple[bool | None, str | None]:
        r = ip_safe_keyword_check(text)
        return r.safe, r.reason
