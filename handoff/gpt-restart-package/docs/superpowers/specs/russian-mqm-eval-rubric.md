# Russian MQM Eval Rubric

Version: `russian-mqm-rubric-v1`

This rubric defines the local, deterministic quality score used for Russian translation QA. It is intentionally dependency-free: no LLM judge, COMET, chrF, BLEU, or network call runs unless an explicit optional adapter is enabled by the caller.

## Goals

- Catch blocking quality defects before a translated file reaches the user.
- Keep scoring stable enough for regression tests.
- Separate literary quality expectations from precision-domain expectations.
- Preserve privacy by reporting issue codes, categories, scores, and sample ids instead of raw document text.

## Tracks

### Literary

Use for prose where voice, imagery, rhythm, dialogue, and natural Russian style matter.

Weights:

- `accuracy`: 0.25
- `fluency`: 0.25
- `style`: 0.20
- `voice`: 0.15
- `terminology`: 0.08
- `structure`: 0.07

### Precision

Use for technical, legal, business, scientific, tabular, or structure-sensitive text.

Weights:

- `accuracy`: 0.35
- `terminology`: 0.22
- `structure`: 0.18
- `fluency`: 0.12
- `style`: 0.08
- `voice`: 0.05

## MQM Categories

- `accuracy`: meaning, facts, numbers, dates, amounts, obligations.
- `terminology`: repeated terms, named entities, domain vocabulary.
- `fluency`: natural Russian grammar and readability.
- `style`: register, idiom, calque avoidance, typography.
- `voice`: narrator or speaker consistency.
- `structure`: headings, lists, paragraphs, navigation, wrappers.
- `protected_content`: URLs, placeholders, identifiers, protected markers.
- `untranslated_text`: source-language residue that should have been translated.

## Scoring

The deterministic evaluator starts at `100.0` and subtracts penalties from quality issues:

- `warning`: 4 points
- `error`: 12 points
- `critical`: 25 points

Category multipliers:

- `protected_content`: `1.25`
- `untranslated_text`: `1.5`

A sample passes only when the score is at least `85.0` and there are no `error` or `critical` issues.

## Optional Metrics

External metrics and LLM-as-judge are adapter-only. They must require explicit opt-in and must record:

- metric or model name;
- metric or prompt version;
- score;
- whether a reference translation was used;
- sample id when available.

The default test path must never require optional packages or network access.
