"""Sourcing layer: match a candidate to a supplier SKU."""

from drift.sourcing.base import SourcingAdapter, SourcingResult
from drift.sourcing.factory import get_sourcing_adapter

__all__ = ["SourcingAdapter", "SourcingResult", "get_sourcing_adapter"]
