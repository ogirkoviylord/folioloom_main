# TXT Format Adapter Slice

## Goal

Start splitting format-specific planning out of `translation_runner.py` without changing user-visible translation behavior.

This first slice handles TXT only because it has the smallest formatting surface and can establish the public adapter contract safely before DOCX/EPUB are moved.

## Scope

- Add shared adapter contracts for text blocks, translation units, and adapter plans.
- Add a TXT adapter planner that preserves the existing paragraph-based fragmenting behavior.
- Make TXT order estimates use the public adapter plan.
- Make persistent TXT job planning use the same adapter plan.
- Keep DOCX/EPUB unchanged in this slice.

## Verification

- Add focused TXT adapter tests for fragment count, reading order, source block ids, prompt tier, adapter version, and estimate fields.
- Keep existing order estimate and persistent planner tests passing.
- Run full unit discovery and compile checks before committing.

## Checklist

- [x] Add adapter contract tests.
- [x] Implement shared contracts and TXT planner.
- [x] Wire TXT estimate and persistent planner to the TXT planner.
- [x] Run targeted tests.
- [x] Run full verification and commit.
