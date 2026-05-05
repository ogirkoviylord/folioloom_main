import unittest

from translator_service.structure_optimizer import (
    PromptTier,
    StructuredTextBlock,
    TextBlockKind,
    build_translation_units,
)


class StructureOptimizerTest(unittest.TestCase):
    def test_batches_adjacent_plain_blocks_up_to_fragment_limit(self):
        units = build_translation_units(
            [
                StructuredTextBlock(index=0, text="First plain paragraph."),
                StructuredTextBlock(index=1, text="Second plain paragraph."),
                StructuredTextBlock(index=2, text="Third plain paragraph."),
            ],
            max_fragment_chars=50,
        )

        self.assertEqual(len(units), 2)
        self.assertEqual([block.index for block in units[0].blocks], [0, 1])
        self.assertEqual([block.index for block in units[1].blocks], [2])
        self.assertEqual(units[0].prompt_tier, PromptTier.PLAIN)

    def test_keeps_structured_group_separate_from_surrounding_plain_text(self):
        units = build_translation_units(
            [
                StructuredTextBlock(index=0, text="Intro."),
                StructuredTextBlock(
                    index=1,
                    text="First row",
                    kind=TextBlockKind.TABLE,
                    group_id="table-1",
                ),
                StructuredTextBlock(
                    index=2,
                    text="Second row",
                    kind=TextBlockKind.TABLE,
                    group_id="table-1",
                ),
                StructuredTextBlock(index=3, text="Outro."),
            ],
            max_fragment_chars=100,
        )

        self.assertEqual(
            [[block.index for block in unit.blocks] for unit in units],
            [[0], [1, 2], [3]],
        )
        self.assertEqual(units[1].prompt_tier, PromptTier.STRICT)

    def test_splits_oversized_structured_group_only_at_block_boundaries(self):
        units = build_translation_units(
            [
                StructuredTextBlock(
                    index=0,
                    text="Column A has a longer text",
                    kind=TextBlockKind.TABLE,
                    group_id="table-1",
                ),
                StructuredTextBlock(
                    index=1,
                    text="Column B has a longer text",
                    kind=TextBlockKind.TABLE,
                    group_id="table-1",
                ),
                StructuredTextBlock(
                    index=2,
                    text="Column C has a longer text",
                    kind=TextBlockKind.TABLE,
                    group_id="table-1",
                ),
            ],
            max_fragment_chars=35,
        )

        self.assertEqual(
            [[block.index for block in unit.blocks] for unit in units],
            [[0], [1], [2]],
        )
        self.assertTrue(all(unit.prompt_tier is PromptTier.STRICT for unit in units))


if __name__ == "__main__":
    unittest.main()
