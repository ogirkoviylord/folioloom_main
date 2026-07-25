from __future__ import annotations

import unittest

from translator_service.document_glossary_editor import (
    OwnerGlossaryEditorInputError,
    build_owner_pinned_glossary_snapshot,
)
from translator_service.glossary_contracts import (
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryLayer,
)
from translator_service.glossary_snapshot_serialization import (
    serialize_glossary_snapshot_v1,
)


class DocumentGlossaryEditorTest(unittest.TestCase):
    def test_builds_canonical_owner_pinned_snapshot(self) -> None:
        first = build_owner_pinned_glossary_snapshot(
            source_language=" en ",
            target_language=" ru ",
            source_terms=("Zeta", "Alpha"),
            target_terms=("Зета", "Альфа"),
            entry_types=("name", "term"),
        )
        second = build_owner_pinned_glossary_snapshot(
            source_language="en",
            target_language="ru",
            source_terms=("Alpha", "Zeta"),
            target_terms=("Альфа", "Зета"),
            entry_types=("term", "name"),
        )

        self.assertEqual(
            serialize_glossary_snapshot_v1(first),
            serialize_glossary_snapshot_v1(second),
        )
        self.assertEqual(first.entries[0].category, GlossaryEntryCategory.TERM)
        self.assertEqual(first.entries[0].layer, GlossaryLayer.HARD)
        self.assertEqual(first.entries[0].status, GlossaryEntryStatus.OWNER_PINNED)
        self.assertEqual(first.entries[0].target_canonical, "Альфа")

    def test_rejects_invalid_or_incomplete_rows(self) -> None:
        for source_terms, target_terms, entry_types in (
            ((), (), ()),
            (("Source",), (), ("term",)),
            (("",), ("Target",), ("term",)),
            (("Source",), ("Target",), ("unsupported",)),
        ):
            with self.subTest(source_terms=source_terms, entry_types=entry_types):
                with self.assertRaises(OwnerGlossaryEditorInputError):
                    build_owner_pinned_glossary_snapshot(
                        source_language="en",
                        target_language="ru",
                        source_terms=source_terms,
                        target_terms=target_terms,
                        entry_types=entry_types,
                    )


if __name__ == "__main__":
    unittest.main()
