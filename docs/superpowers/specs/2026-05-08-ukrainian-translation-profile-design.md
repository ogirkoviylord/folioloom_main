# Ukrainian Translation Profile Design

## Goal

Add a full Ukrainian translation profile with the same architectural weight as the existing Russian profile. The first implementation should make Ukrainian target-language prompting deterministic, cache-aware, and source-pair aware, while keeping the broader translation runner, document adapters, and safety policies unchanged.

This design uses the Ukrainian methodology in `docs/superpowers/specs/ukrainian-translation-profile.md` as the editorial source of truth and the current Russian implementation in `translation_profiles.py` and `source_pair_profiles.py` as the technical pattern.

## Current Baseline

Ukrainian is already a supported target language in the UI and language-name helpers, but the quality profile layer is still Russian-only:

- `get_target_language_profile("uk")` returns `None`.
- `target_language_policy_signature("uk")` returns `target-profile:default-v1`.
- `build_target_language_profile_prompt(target_language="uk", ...)` returns an empty string.
- `build_source_pair_profile_prompt("en", "uk")` returns an empty string because source-pair profiles are gated to Russian targets.
- Existing tests intentionally assert that non-Russian targets have no profile; those assertions need to become narrower and target only languages that still lack profiles.

## Normative Baseline

The profile should cite and follow the current official state-language standard `Український правопис`, approved by the National Commission on State Language Standards by Decision No. 47 of 1 March 2026 and in force from 28 March 2026.

The Ministry of Education and Science states that the 2026 standard introduced editorial and technical corrections and did not change established spelling rules for users. Implementation should therefore use the 2026 standard as the current name of the norm, not the older shorthand `правопис 2019`.

Sources:

- National Commission on State Language Standards: https://mova.gov.ua/diyalnist-i-proyekti/termini/pravopys-ukrainskoi-movy
- Ministry of Education and Science: https://mon.gov.ua/news/nabrav-chynnosti-standart-derzhavnoi-movy-ukrainskyi-pravopys

## Architecture

### Target-Language Profile

Extend `translation_profiles.py` with `UKRAINIAN_PROFILE = TargetLanguageProfile(...)`.

Initial profile identity:

- `language_code`: `uk`
- `version`: `ukrainian-v1`
- cache signature: `target-profile:uk:ukrainian-v1`

`get_target_language_profile()` should normalize language tags the same way existing callers do and return the Ukrainian profile for `uk` and likely regional forms such as `uk-UA` if passed through. Russian behavior must remain unchanged.

### Prompt Builder Generalization

`build_target_language_profile_prompt()` currently hardcodes Russian labels:

- `Target-language policy: Russian target-language profile ...`
- `Default Russian rules: ...`
- `Russian naturalness examples: ...`

The builder should use profile metadata instead of hardcoded Russian strings. Add a display name field or derive it from `language_code`:

- Russian -> `Russian`
- Ukrainian -> `Ukrainian`

Expected prompt shape:

```text
Target-language policy: Ukrainian target-language profile ukrainian-v1.
Detected text type: technical.
Text-type instruction: ...
Precision Ukrainian quality track: ...
Default Ukrainian rules: ...
Named entity rules: ...
Terminology rules: ...
Term examples: ...
Ukrainian naturalness examples: ...
Protected-term grammar examples: ...
```

This avoids adding a separate prompt function for Ukrainian and keeps future language profiles cheap to add.

### Quality Tracks

The current `RussianQualityTrack` enum is functionally generic (`LITERARY`, `PRECISION`) but named Russian. For the first Ukrainian profile, do not block on a large refactor. Reuse the same enum in prompt-profile rules, but phrase the Ukrainian rules as Ukrainian-specific:

- `LITERARY`: preserve voice, rhythm, dialogue, imagery, ambiguity, narrator perspective, and author style; allow natural Ukrainian restructuring.
- `PRECISION`: prioritize terminology, dates, numbers, obligations, structure, code, URLs, IDs, placeholders, tables, lists, and exact named entities.

Follow-up refactor: rename the enum to `TranslationQualityTrack` or introduce a generic wrapper after Ukrainian is working. That can be a separate change because it touches policy signatures, tests, and cache behavior.

## Ukrainian Profile Content

### Default Rules

The default rules should tell the model:

- Write natural contemporary standard Ukrainian according to the current official Ukrainian orthography standard.
- Avoid Russian calques, surzhyk, English word order, literal phrasal translations, and awkward nominalizations.
- Preserve meaning, tone, author voice, paragraph boundaries, and document structure.
- Do not add explanations or simplify specialized content unless the source does so.

### Named Entity Rules

Use the same entity categories as Russian, with Ukrainian-specific decisions:

- Preserve brands, product names, legal company names, URLs, usernames, code identifiers, API names, package names, commands, flags, filenames, and environment variables.
- Transcribe ordinary personal names for Ukrainian readers when the document is not a legal identity, citation, username, email, or code-owner context.
- Use established Ukrainian country and city names where they exist; preserve exact address components when precision matters.
- Preserve official names and legal suffixes unless a glossary or legal-localization setting overrides them.

### Terminology Rules

Core rules:

- Use stable Ukrainian technical terminology where it is natural.
- Preserve exact English technical terms only when they are protected names, API references, or code-like identifiers.
- Keep terminology choices consistent throughout the document.
- Avoid English false friends and Russian calques.

Initial term examples:

- `query parameters -> параметри запиту`
- `regular expression -> регулярний вираз`
- `footnote -> виноска`
- `endnote -> кінцева виноска by context`
- `tracked changes -> виправлення or відстежені зміни by context`
- `section break -> розрив розділу`
- `table of contents -> зміст`
- `placeholder -> заповнювач in general UI context, плейсхолдер in technical UI/LLM context`
- `prompt -> промпт in LLM context, підказка only for user hints`
- `token -> токен in LLM/API/security context`
- `callback -> callback for exact code/API reference, зворотний виклик or колбек in explanatory prose by context`
- `endpoint -> endpoint for exact API references, кінцева точка or glossary-pinned ендпоінт in explanatory prose`
- `framework -> фреймворк`

### Naturalness Examples

The profile should explicitly ban common high-risk outputs:

- Do not translate `made a decision` as `зробив рішення`; prefer `вирішив` or `ухвалив рішення` by register.
- Do not translate `participate` as `приймати участь`; use `брати участь`.
- Do not translate `during/over` as `на протязі` unless the source literally describes physical draft/extension; use `протягом`.
- Do not translate `is/constitutes` as `являється`; use `є`, a verb, or a natural Ukrainian construction.
- Avoid English sentence order when Ukrainian would naturally use a different clause structure.

### Text Type Rules

Populate every `TextType` currently used by the Russian profile:

- `GENERAL`: clear contemporary Ukrainian with moderate rewriting for natural Ukrainian syntax.
- `LITERARY_FICTION`: preserve voice, rhythm, dialogue, imagery, irony, ambiguity, and narrator perspective.
- `LITERARY_NON_FICTION`: preserve author voice while producing polished editorial Ukrainian.
- `JOURNALISTIC_PUBLICISTIC`: use readable Ukrainian publicistic style and preserve facts, attribution, dates, and quotes.
- `SCIENTIFIC_ACADEMIC`: preserve claims, hedging, citations, units, formulas, and exact terminology.
- `TECHNICAL`: be concise; preserve code identifiers, API names, package names, filenames, command flags, environment variables, and product names.
- `BUSINESS_LEGAL_LIKE`: use formal Ukrainian without creative paraphrase; preserve obligations, defined terms, dates, amounts, and legal entity names.
- `EDUCATIONAL`: use clear explanatory Ukrainian and translate descriptive learning headings.
- `MARKETING`: use idiomatic Ukrainian marketing copy without inventing claims, benefits, urgency, or guarantees.
- `MIXED_UNKNOWN`: use conservative general Ukrainian with technical and named-entity protections enabled.

### Protected-Term Grammar

Use Ukrainian support nouns instead of modifying protected terms:

- `модуль FastAPI`
- `пакет requests`
- `метод callback`
- `змінна PATH`
- `команда git commit`

Do not add Ukrainian endings inside inline code, API names, package names, URLs, commands, or protected markers.

## Source-Pair Profiles

Remove the Russian-only target gate in `source_pair_profiles.py` and let the lookup key decide whether a source-pair profile exists.

Initial Ukrainian source pairs:

### English -> Ukrainian

Instruction goals:

- Translate meaning into idiomatic Ukrainian.
- Avoid English word order, mechanical possessives, article-like phrasing, literal phrasal verbs, and Title Case capitalization.
- Resolve false friends by context: `actual`, `accurate`, `eventually`, `control`, `regular`, `data`, `decade`, `magazine`.
- Preserve protected code/API/URL identifiers.

Signature: `source-pair:en-uk:v1`

### Russian -> Ukrainian

Instruction goals:

- Translate close Slavic wording into standard Ukrainian, not word-by-word replacement.
- Avoid Russian syntax calques, surzhyk, and common lexical calques such as `приймати участь`, `на протязі`, `являється`, `слідуючий`.
- Do not preserve Russian words unless they are names, citations, usernames, addresses, legal identities, or protected text.
- Preserve tone and register without over-formalizing shared phrasing.

Signature: `source-pair:ru-uk:v1`

### Auto/Mixed -> Ukrainian

Instruction goals:

- Use `source_language` hints when present.
- Do not assume English.
- Translate every human-language span into Ukrainian, including secondary languages.
- Keep labels consistent in Ukrainian while preserving protected markers, code, URLs, placeholders, exact identifiers, and intentional names.

Signature: `source-pair:auto-uk:v1`

### Later Pairs

Polish, Dutch, German, French, and Spanish to Ukrainian can be added after the first profile lands, using the methodology document for guidance. The lookup should already support them so new entries require only data and tests.

## Tests

Use TDD for implementation.

### `tests/test_translation_profiles.py`

Add tests that assert:

- `get_target_language_profile("uk")` returns a profile.
- `get_target_language_profile("uk-UA")` returns the Ukrainian profile if regional normalization is implemented.
- Ukrainian version is `ukrainian-v1`.
- term examples include `заповнювач`, `плейсхолдер`, `endpoint`, and `параметри запиту`.
- `target_language_policy_signature("uk") == "target-profile:uk:ukrainian-v1"`.
- Ukrainian technical prompt includes `Ukrainian target-language profile`, `standard Ukrainian`, `avoid Russian calques`, `technical documentation`, `preserve code identifiers`, `API names`, and protected grammar examples.
- Ukrainian literary prompt includes `Literary Ukrainian quality track`, `voice, rhythm, dialogue, imagery`, and naturalness examples such as `зробив рішення`, `брати участь`, and `протягом`.
- A language without a profile, such as `en`, still returns `None` and emits an empty prompt.

### `tests/test_source_pair_profiles.py`

Update the old `en -> uk` empty-profile assertion. Add tests for:

- English to Ukrainian guidance.
- Russian to Ukrainian guidance.
- Mixed/auto to Ukrainian guidance.
- Stable signatures for `en-US -> uk-UA`, `ru -> uk`, and `auto -> uk`.
- Non-profiled target/source pairs still return `source-pair:none` where no fallback exists.

### `tests/test_translation_policy.py`

Add a system-prompt test confirming Ukrainian target-language profile guidance appears in the full translation prompt before or alongside source-pair guidance.

### Cache Tests

If existing cache tests cover target-language policy changes generically, add only one Ukrainian assertion. Otherwise add a test that changing `ukrainian-v1` to a hypothetical `ukrainian-v2` changes the policy signature.

## Implementation Order

1. Write failing tests for the Ukrainian target profile.
2. Generalize prompt labels in `build_target_language_profile_prompt()`.
3. Add `UKRAINIAN_PROFILE`.
4. Verify target-profile tests pass.
5. Write failing tests for Ukrainian source-pair profiles.
6. Remove the Russian-only gate in `source_pair_profiles.py`.
7. Add `en/ru/auto -> uk` profile entries.
8. Verify source-pair tests pass.
9. Add full-system prompt and cache assertions.
10. Run the focused test set:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_translation_profiles \
  tests.test_source_pair_profiles \
  tests.test_translation_policy \
  tests.test_translation_cache
```

## Out Of Scope For First Implementation

- A dedicated Ukrainian deterministic QA module.
- Ukrainian regression corpus generation for DOCX/EPUB/TXT.
- Renaming `RussianQualityTrack` to a generic enum.
- User-facing advanced controls for glossary, terminology mode, or named-entity mode.
- Adding all future source pairs in the first patch.

These should follow once the prompt profile is stable.

## Acceptance Criteria

- Ukrainian target-language prompt is non-empty and includes current orthography, naturalness, terminology, entity, text-type, quality-track, and protected-grammar rules.
- Ukrainian policy signature is stable and distinct from the default profile.
- English, Russian, and mixed-source documents get Ukrainian source-pair guidance.
- Existing Russian profile prompts and source-pair signatures remain unchanged.
- Languages without a target profile continue to use the default profile behavior.
- Focused tests pass.
