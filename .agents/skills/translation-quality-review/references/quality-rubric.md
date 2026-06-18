# Translation Quality Rubric

Use this reference only when a translation review needs more detail than the default checklist.

## Severity

- `Critical`: missing large passages, fabricated content, wrong meaning that changes facts/plot/instructions, large untranslated passages, broken navigation/structure, provider meta text in final output, or unusable output.
- `Major`: repeated terminology/name inconsistency, misleading phrasing, style/voice drift that harms reading, broken paragraph/chapter alignment, duplicated/reordered blocks, or meaningful omissions/additions.
- `Minor`: awkward phrasing, isolated literal translation, punctuation/typography issue, small register mismatch, local repetition, or weak sentence flow.
- `Note`: subjective editorial preference or optional polish.

## Document Profiles

- Book/manuscript: prioritize scene meaning, chapter continuity, dialogue, voice, names, places, forms of address, cultural references, omissions and literary fluency.
- Business document: prioritize obligations, dates, numbers, entities, definitions, tables, lists and ambiguity. Do not give legal advice.
- Technical document: prioritize commands, code, paths, configuration keys, UI labels, product names, units, warnings and step order.
- Editorial/article: prioritize argument flow, factual meaning, headline/subheading fit, quoted material, tone and readability.
- Generic: prioritize meaning preservation, terminology, structure and fluency.

## Pipeline Regression Signals

Treat these as likely system defects, not merely editorial issues:

- missing, duplicated or reordered source blocks;
- provider commentary, apologies, markdown wrappers or explanations in final text;
- untranslated block clusters after a pipeline or prompt change;
- broken EPUB navigation, headings, metadata or chapter boundaries;
- glossary terms applied to structural labels or proper nouns incorrectly;
- good isolated translation but bad assembled output.

Likely owners:

- provider output;
- prompt/policy/profile;
- glossary/prepared package;
- assembly;
- format adapter;
- source ambiguity;
- human editorial quality.

## Fix Types

- `retranslate block`: meaning was lost, changed, omitted or fabricated.
- `human edit`: meaning is mostly correct but style, tone or fluency is weak.
- `terminology pass`: names, forms of address or repeated terms need normalization.
- `format repair`: headings, lists, tables, footnotes, metadata, navigation or chapter structure need correction.
- `pipeline bug`: missing, duplicated, reordered, wrapped or contaminated output suggests system behavior.
- `source clarification`: source is ambiguous, corrupt or incomplete.
- `accept as-is`: issue is subjective or low-value polish.

## Evidence

Use short excerpts in normal reports. In owner-local chat, raw excerpts may be longer when needed to diagnose the issue, but do not move that raw material into commits, public docs, GitHub issues/PRs, release artifacts or external services without exact owner intent.
