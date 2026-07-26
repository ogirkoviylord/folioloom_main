"""Build the narrow owner-pinned snapshot accepted by the durable editor."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossaryLayer,
    GlossarySnapshot,
)


@dataclass(frozen=True)
class OwnerGlossaryEditorInputError(ValueError):
    """The POST-only editor input cannot produce a durable snapshot."""


def build_owner_pinned_glossary_snapshot(
    *,
    source_language: str,
    target_language: str,
    source_terms: Sequence[str],
    target_terms: Sequence[str],
    entry_types: Sequence[str],
) -> GlossarySnapshot:
    """Canonicalize supported owner rows without creating raw diagnostics."""
    source_language = _required_text(source_language)
    target_language = _required_text(target_language)
    if not (
        len(source_terms) == len(target_terms) == len(entry_types)
        and source_terms
    ):
        raise OwnerGlossaryEditorInputError()

    rows = []
    for source_term, target_term, entry_type in zip(
        source_terms, target_terms, entry_types, strict=True
    ):
        source_term = _required_text(source_term)
        target_term = _required_text(target_term)
        if entry_type not in {"term", "name"}:
            raise OwnerGlossaryEditorInputError()
        rows.append((source_term, target_term, entry_type))
    rows.sort()

    evidence = tuple(
        GlossaryEvidenceRef(
            evidence_id=f"owner-pin-{index}",
            evidence_type=GlossaryEvidenceType.OWNER_PIN,
            unit_sequence=0,
            source_block_id=f"owner-pinned-{index}",
            source_scope="document",
            surface=GlossaryEvidenceSurface.UNKNOWN,
        )
        for index, _row in enumerate(rows, start=1)
    )
    entries = tuple(
        GlossaryEntry(
            entry_id=f"owner-entry-{index}",
            category=(
                GlossaryEntryCategory.TERM
                if entry_type == "term"
                else GlossaryEntryCategory.NAME
            ),
            layer=GlossaryLayer.HARD,
            status=GlossaryEntryStatus.OWNER_PINNED,
            source_canonical=source_term,
            target_canonical=target_term,
            evidence_refs=(f"owner-pin-{index}",),
            confidence=1.0,
        )
        for index, (source_term, target_term, entry_type) in enumerate(rows, start=1)
    )
    snapshot_id = "owner-glossary-" + hashlib.sha256(
        json.dumps(
            [source_language, target_language, rows],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return GlossarySnapshot(
        snapshot_id=snapshot_id,
        source_language=source_language,
        target_language=target_language,
        entries=entries,
        evidence=evidence,
    )


def _required_text(value: str) -> str:
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise OwnerGlossaryEditorInputError()
    return normalized
