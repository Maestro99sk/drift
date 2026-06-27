"""Dossier layer: Claude assembles the go/no-go selling plan."""

from drift.dossier.base import DossierAdapter, DossierDraft
from drift.dossier.factory import get_dossier_adapter

__all__ = ["DossierAdapter", "DossierDraft", "get_dossier_adapter"]
