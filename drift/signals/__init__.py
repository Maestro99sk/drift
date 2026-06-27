"""Signal layer: ingest trends from legitimate sources."""

from drift.signals.base import RawSignal, SignalAdapter
from drift.signals.factory import get_signal_adapter

__all__ = ["RawSignal", "SignalAdapter", "get_signal_adapter"]
