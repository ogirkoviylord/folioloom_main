# Russian Translation Profile

This profile defines how the service should translate documents into Russian. It is the first target-language quality profile and is used to validate the broader language-profile architecture before the same process is applied to other target languages.

The profile is intentionally layered: universal document-safety rules remain shared, while Russian-specific decisions live here.

## Status

- Priority: first quality-development target language.
- Rollout stage: design draft, not production-ready.
- Target audience: Russian-speaking readers of books, long-form texts, technical materials, business documents, educational content, and publicistic texts.
- Common source languages: English first; Ukrainian, Polish, Dutch, French, Spanish, German, and mixed-language documents next.
- Most important document types: TXT, DOCX, EPUB.
- Current quality goal: create enough decisions and samples to implement a Russian target-language profile through tests instead of ad hoc prompt edits.

Russian is first because it is practical for fast manual QA and exposes hard translation-policy problems early: English calques, technical terminology, transliteration, named entities, inflection around preserved terms, and book-style naturalness. It is not defined as the main market.

## Shared Rules Inherited From The Core

The Russian profile must not override these shared rules unless a documented exception exists:

- preserve document structure, paragraph boundaries, tables, headers, footers, notes, comments, EPUB spine order, and internal batch markers;
- keep `ZXQPROTECTED...QXZ` markers unchanged;
- preserve URLs, email addresses, usernames, code identifiers, package names, API names, commands, JSON/XML/HTML/YAML syntax, placeholders, and environment variables;
- prevent provider commentary, apologies, markdown fences, warnings, and internal markers from leaking into translated files;
- keep cancellation, partial result, retry, resume, and translation-cache behavior stable.

## Default Behavior

- General: produce natural modern Russian, avoid English word order and literal calques, keep meaning and tone without unnecessary embellishment.
- Technical: prefer stable Russian IT terminology, preserve code/API/package identifiers, preserve or transliterate established English terms when literal translation would sound artificial.
- Literary: preserve voice, rhythm, dialogue, imagery, and author style; avoid flattening prose into neutral explanatory Russian.
- Business/legal-like: preserve entities, dates, amounts, obligations, defined terms, and formal tone; avoid creative paraphrase.
- Scientific/academic: preserve exact claims, hedging, citations, units, formulas, and terminology; avoid popularizing the style unless the source is popular science.
- Journalistic/publicistic: preserve factual clarity, attribution, dates, names, and readable Russian publicistic rhythm; avoid both bureaucratic heaviness and clickbait exaggeration.
- Marketing: preserve persuasive intent and idiomatic Russian copy, but do not invent claims, guarantees, or benefits absent from the source.
- Mixed/unknown: use conservative general Russian with technical/entity protections enabled.

## Target-Language Naturalness

Russian output should sound like a text originally edited in Russian, not like English syntax with Russian words.

- Rewrite sentence order when English or Dutch source order is unnatural in Russian.
- Prefer verbs and concrete nouns over heavy nominalizations in ordinary prose.
- Avoid mechanical `his/her/their`; use a Russian noun phrase or omit when clear.
- Avoid unnecessary pronouns where Russian naturally drops them.
- Preserve author voice in literary text, but do not add explanations.
- Do not over-Russify technical identifiers or official names.

Examples:

- Bad literal: `Он сделал решение использовать фреймворк.`
- Neutral: `Он принял решение использовать фреймворк.`
- Better technical/editorial: `Он решил использовать фреймворк.`

- Bad literal: `Это высокоуровневый обзор системы.`
- Neutral: `Это обзор системы на высоком уровне.`
- Better general: `Это общее описание системы.`

## Text Type Profiles

- General prose: natural, clear, contemporary Russian; moderate paraphrase for Russian syntax; preserve official names and translate descriptive titles when not protected.
- Literary fiction: preserve voice, register, rhythm, dialogue, imagery, irony, and ambiguity; transliterate personal names unless a canonical Russian form exists.
- Literary non-fiction: clear editorial Russian with author voice preserved; medium terminology strictness.
- Journalistic/publicistic: readable publicistic Russian; preserve facts, dates, attributions, and quotes.
- Scientific/academic: precise academic Russian; preserve claims, uncertainty, citations, units, formulas, and terminology.
- Technical documentation: concise technical Russian; preserve code, APIs, package names, filenames, command flags, env vars, and product names.
- Business/legal-like: formal Russian without unnecessary bureaucracy; preserve obligations, definitions, dates, amounts, and entity names.
- Educational: clear explanatory Russian; translate descriptive learning headings.
- Marketing: idiomatic Russian marketing copy without invented claims.
- Mixed/unknown: conservative general Russian with technical/entity protections enabled.

## Terminology

Default policy: preserve technical precision, use established Russian equivalents where natural, and avoid inconsistent switching between translation, transliteration, and preservation.

### Preserve

- API names, package names, library names, model names, product identifiers, environment variables, command names, flags, filenames, code symbols;
- URLs, emails, usernames, issue IDs, document-control labels;
- registered brand and product names.

### Translate

- `query parameters` -> `параметры запроса`;
- `regular expression` -> `регулярное выражение`;
- `footnote` -> `сноска`;
- `endnote` -> `концевая сноска` or `затекстовая сноска` depending on context;
- `tracked changes` -> `исправления` or `отслеживаемые изменения` depending on UI/document context;
- `section break` -> `разрыв раздела`;
- `merge cells` -> `объединение ячеек`.

### Transliterate Or Transcribe

- `prompt` -> `промпт` for LLM/product context; `подсказка` only when the source means a user hint rather than an LLM instruction;
- `token` -> `токен` for LLM/API/security context; `маркер` only when source means a visible marker;
- `placeholder` -> `плейсхолдер` in technical UI/LLM context; `заполнитель` in general UI text; avoid `местозаполнитель` unless glossary-pinned;
- `framework` -> `фреймворк`;
- `callback` -> `callback` for code/API reference, `колбэк` in explanatory prose;
- `endpoint` -> `endpoint` for API references, `эндпоинт` in explanatory technical prose.

### Glossary Required

Use glossary-pinned forms for product UI terms, book series names, company-specific terminology, recurring technical terms such as `prompt tier`, `translation memory`, `protected markers`, official legal names, and institutions.

### False Friends

- `actual` -> usually `фактический`, `реальный`, `действительный`; not automatically `актуальный`;
- `accurate` -> `точный`; not `аккуратный` unless about neatness;
- `eventually` -> `в итоге`, `со временем`; not `эвентуально`;
- `control` -> `управление`, `проверка`, `контроль` depending on context;
- `data` -> `данные`, usually plural agreement in Russian editorial style;
- `public` -> `общедоступный`, `публичный`, `общественный` depending on context;
- `regular` -> `обычный`, `регулярный`, `штатный` depending on context.

## Named Entities

- Personal names: transliterate/transcribe ordinary names for Russian readers; preserve original spelling in citations, bibliography, legal identity, usernames, emails, code owners, and handles; prefer canonical Russian forms when they exist.
- Brands: preserve original brand spelling; do not translate registered brands.
- Products: preserve official names; translate generic descriptive categories around the name.
- Companies/legal names: preserve legal names and suffixes such as `LLC`, `Inc.`, `GmbH`, `B.V.` unless a legal-localization setting exists.
- Institutions/organizations: preserve official names; translate descriptive names when no official branding is implied.
- Cities/countries: use established Russian forms when they exist, for example `Netherlands` -> `Нидерланды`, `Germany` -> `Германия`, `Amsterdam` -> `Амстердам`.
- Streets/addresses: default transliterate/transcribe for readability while preserving exact address components when delivery/legal precision matters.
- Titles: preserve official/branded titles; translate descriptive titles; future setting may use translated title with original in parentheses.
- Links/anchors: preserve URLs; translate ordinary prose anchors; protect product names, commands, IDs, and UI labels.
- Code/API/package names: always preserve exact spelling.

## Typography

- Quotes: use Russian guillemets `«...»` for ordinary prose when typography normalization is safe.
- Dashes: use em dash with spaces in prose where safe; preserve protected hyphens, ranges, IDs, command flags, and table spacing.
- Title capitalization: convert English Title Case to Russian sentence-style capitalization unless preserving an official title.
- Apostrophes: preserve in names and code; avoid introducing apostrophes in Russian transliteration unless canonical.
- Dates, units, numbers: preserve exact forms in legal/business/scientific data; localize only when policy allows it.
- Lists: preserve numbering, bullets, and hierarchy.

## Protected Text Grammar

- Prefer a Russian generic noun around preserved foreign terms when inflection is needed: `модуль FastAPI`, `пакет requests`, `метод callback`.
- Do not alter inline code or protected identifiers to add Russian endings.
- Use inflected transliteration for common borrowed technical terms when allowed: `фреймворка`, `токена`, `эндпоинта`, `промпта`.
- If a preserved brand or API name needs a case ending, rewrite the sentence around it.
- Keep punctuation outside protected inline code where possible.

Examples:

- Awkward: `с помощью framework`
- Better: `с помощью фреймворка`
- Better when preserving official name: `с помощью фреймворка FrameworkName`

- Awkward: `вызовите callback`
- Better explanatory: `вызовите callback-функцию`
- Better prose: `вызовите колбэк`

## Source Pair Exceptions

- English -> Russian: avoid English word order, mechanical possessives, false friends, and Title Case; preserve code/API/URL identifiers.
- Ukrainian -> Russian: do not over-normalize shared Slavic structures into stiff Russian; preserve names according to document type.
- Polish -> Russian: handle `Zażółć gęślą jaźń` as a letter/diacritic test, not literal prose.
- Dutch -> Russian: split compounds by meaning; handle `Nederlands:` as `Нидерландский:` when labels remain useful; preserve `B.V.` in company names.
- French/Spanish/German -> Russian: preserve official names and accents in brands/citations/legal names; use established Russian country/city names.
- Mixed source -> Russian: translate all human-language segments, preserve protected technical fragments, and preserve/regenerate language labels consistently.

## Document Format Risks

- TXT: preserve blank-line paragraph flow and avoid added explanations.
- DOCX: Russian length and word order can disrupt run-level formatting; preserve structure first, translate tables, pseudo-tables, headers, footers, notes, comments, subscript/superscript, formulas, IDs, repeated spacing, and protected tokens without leaking markers.
- EPUB: preserve XHTML inline elements and spine order; captions and notes may need stricter translation than body prose.
- Future OCR/PDF: Russian OCR language pack and Cyrillic fonts are required before production-bound scanned/PDF output.
- Subtitles: Russian often expands compared with English, so subtitle mode should prefer concise Russian while preserving timing.
- CSV/TSV: preserve row/column count and machine-readable keys unless structured-value translation is explicitly enabled.

## User Controls

Current: user chooses target language only.

Future simple presets:

- `Natural Russian`;
- `Technical Russian`;
- `Literary Russian`;
- `Preserve names`;
- `Transliterate names`;
- `Use glossary`.

Future advanced controls:

- technical terms: preserve, translate, transliterate, glossary;
- personal names: preserve, transliterate, canonical Russian form, original in parentheses;
- brands/products/companies: preserve, glossary;
- streets/addresses: preserve exact, transliterate, translate descriptive parts;
- titles: preserve, translate, translated with original in parentheses;
- text type override: general, technical, literary, business/legal-like, scientific, journalistic, marketing, mixed.

## Regression Samples

### Ordinary Prose

Source: `He made a decision after a high-level overview of the system.`

Expected: avoid `сделал решение`; avoid awkward `высокоуровневый обзор` unless explicitly technical.

Acceptable: `Он принял решение после общего обзора системы.`

### Literary

Source: `The room held its breath while the rain traced silver lines across the window.`

Expected: preserve imagery and rhythm; do not flatten to technical description.

Quality target: `Комната словно затаила дыхание, пока дождь чертил серебряные линии на стекле.`

### Technical

Source: `Set the API endpoint and pass the placeholder token to the callback handler.`

Expected: preserve `API`; choose consistent terms for `endpoint`, `placeholder`, `token`, and `callback`.

Possible output: `Укажите API endpoint и передайте токен-плейсхолдер в callback-обработчик.`

Alternative glossary-driven output may use `эндпоинт`, `плейсхолдер`, and `колбэк`.

### Business/Legal-Like

Source: `Acme B.V. shall deliver the materials by 15 March 2026.`

Expected: preserve legal company name, date, and obligation.

Possible output: `Acme B.V. обязуется предоставить материалы до 15 марта 2026 года.`

### Scientific

Source: `The results suggest a moderate correlation, but the sample size limits the conclusion.`

Expected: preserve hedging and do not overstate claim.

Possible output: `Результаты указывают на умеренную корреляцию, однако размер выборки ограничивает достоверность вывода.`

### Journalistic

Source: `Officials said the policy would be reviewed after public consultations.`

Expected: preserve attribution and publicistic clarity.

Possible output: `Чиновники заявили, что политику пересмотрят после общественных консультаций.`

### Mixed-Language

Source: `English: The endpoint failed. Polski: Zażółć gęślą jaźń. Nederlands: De klant bevestigde de bestelling.`

Expected: translate all human-language segments into Russian, preserve or regenerate labels, treat Polish pangram as an orthographic sample.

### Named Entities

Source: `Maria Johnson visited Baker Street and met the OpenAI Research team.`

Expected: transliterate ordinary personal name, handle street according to address/title policy, preserve `OpenAI`.

### Protected Content

Source: `Set ${API_TOKEN}, call https://example.com/v1/items, and keep ROW-001 unchanged.`

Expected: protected content remains byte-for-byte unchanged while surrounding prose becomes Russian.

### Headings And Title Case

Source: `Translation Quality Roadmap`

Expected: Russian capitalization should be sentence-style unless official title preservation applies.

Possible output: `Дорожная карта качества перевода`

### DOCX

Required sample coverage: headings, paragraphs, table cells, pseudo-table row, hyperlink visible text, footnote, endnote, comment, subscript/superscript, mixed-language paragraph, protected technical tokens.

### EPUB

Required sample coverage: spine order, chapter heading, paragraph prose, inline `strong` and `em`, link, caption or footnote-like block, mixed-language paragraph.

## Acceptance Notes

### Beta-Ready Gaps

- Create actual TXT, DOCX, and EPUB Russian sample pack files.
- Add automated tests for deterministic Russian exceptions and protected grammar cases.
- Add prompt/profile implementation plan after this profile is reviewed.
- Run manual QA on at least one medium-length English -> Russian document.

### Production-Ready Gaps

- Store selected Russian profile and policy fields with jobs.
- Include policy fields in translation-cache keys.
- Add user-facing presets or explicitly defer them.
- Validate DOCX and EPUB structure preservation on real documents.
- Collect beta feedback and update terminology defaults.
