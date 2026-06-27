"""Execution layer: owner-approved publish + ads + fulfilment.

Each sub-adapter is feature-flagged: dormant unless its credential is set, OR mocked
explicitly. Nothing runs without an approved dossier (section 9 hard guardrail).
"""

from drift.execution.factory import (
    get_ads_adapter,
    get_fulfilment_adapter,
    get_storefront_adapter,
)

__all__ = ["get_ads_adapter", "get_fulfilment_adapter", "get_storefront_adapter"]
