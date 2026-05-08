# Ukrainian Translation Profile

This profile defines how the service should translate documents into Ukrainian. It is designed as a full target-language quality profile, parallel to the Russian profile, so future implementation can use the same architecture: shared document-safety rules, target-language rules, source-pair rules, regression samples, and later deterministic quality checks.

The profile does not teach the translation model Ukrainian from scratch. It gives the model an editorial policy: what kind of Ukrainian is acceptable, what must be preserved, what should be translated, which common calques and false friends to avoid, and how to handle protected technical text without damaging grammar.

## Normative Baseline

- Use the current official state-language standard `Український правопис`, approved by the National Commission on State Language Standards by Decision No. 47 of 1 March 2026 and in force from 28 March 2026.
- The Ministry of Education and Science notes that the 2026 standard introduced editorial and technical corrections to the text and did not change established spelling rules for users.
- Practical implementation should therefore follow current standard Ukrainian spelling, while keeping document adapters responsible for layout-sensitive characters and protected text.

References:

- National Commission on State Language Standards: https://mova.gov.ua/diyalnist-i-proyekti/termini/pravopys-ukrainskoi-movy
- Ministry of Education and Science of Ukraine: https://mon.gov.ua/news/nabrav-chynnosti-standart-derzhavnoi-movy-ukrainskyi-pravopys

## Status

- Priority: second full quality-development target language after Russian.
- Rollout stage: design draft, not production-ready.
- Target audience: Ukrainian-speaking readers of books, long-form documents, technical manuals, business documents, publicistic texts, educational materials, and product content.
- Common source languages: English, Russian, mixed-language documents first; Polish, Dutch, German, French, and Spanish next.
- Most important document types: TXT, DOCX, EPUB.
- Current quality goal: create explicit Ukrainian translation decisions that can later become prompt rules, cache signatures, regression samples, and QA checks.

Ukrainian is high priority because it is already a supported target language in the product UI and because it exposes a different quality risk than Russian: the model may produce understandable Ukrainian while still carrying Russian calques, surzhyk, English word order, or unstable technical terminology.

## Shared Rules Inherited From The Core

The Ukrainian profile must not override these shared rules unless a documented exception exists:

- preserve document structure, paragraph boundaries, tables, headers, footers, notes, comments, EPUB spine order, and internal batch markers;
- keep `ZXQPROTECTED...QXZ` markers unchanged;
- preserve URLs, email addresses, usernames, code identifiers, package names, API names, commands, JSON/XML/HTML/YAML syntax, placeholders, and environment variables;
- prevent provider commentary, apologies, markdown fences, warnings, and internal markers from leaking into translated files;
- keep cancellation, partial result, retry, resume, and translation-cache behavior stable.

## Default Behavior

- General: produce natural contemporary standard Ukrainian; avoid Russian calques, surzhyk, English word order, literal phrasal translations, and awkward nominalizations.
- Technical: prefer stable Ukrainian technical terminology; preserve code/API/package identifiers; preserve exact English terms where they are protected names or API references.
- Literary: preserve voice, rhythm, dialogue, imagery, ambiguity, and narrator perspective; do not flatten prose into explanatory Ukrainian.
- Business/legal-like: preserve entities, dates, amounts, obligations, definitions, and formal tone; avoid creative paraphrase.
- Scientific/academic: preserve exact claims, hedging, citations, units, formulas, and terminology; do not popularize unless the source is popular science.
- Journalistic/publicistic: preserve factual clarity, attribution, dates, names, quotations, and readable Ukrainian publicistic rhythm.
- Educational: use clear explanatory Ukrainian and translate descriptive learning headings.
- Marketing: use idiomatic Ukrainian marketing copy, but do not invent claims, benefits, guarantees, or urgency absent from the source.
- Mixed/unknown: use conservative general Ukrainian with technical and named-entity protections enabled.

## Target-Language Naturalness

Ukrainian output should sound like a text originally edited in Ukrainian, not like English or Russian syntax with Ukrainian words.

- Rewrite sentence order when the source order is unnatural in Ukrainian.
- Prefer Ukrainian verbs and clear clauses over heavy noun chains.
- Avoid Russian syntactic calques and surzhyk.
- Avoid mechanical English possessives and article-like phrasing.
- Preserve author voice in literary text without adding explanations.
- Do not over-Ukrainianize protected technical identifiers or official names.
- Use current Ukrainian standard spelling, including forms such as `проєкт` where appropriate.

Examples:

- Bad Russian calque: `Він прийняв участь у зустрічі на протязі тижня.`
- Better: `Він узяв участь у зустрічі протягом тижня.`

- Bad literal: `Це являється високорівневим оглядом системи.`
- Neutral: `Це огляд системи на високому рівні.`
- Better general: `Це загальний огляд системи.`

- Bad English calque: `Вона зробила рішення використовувати фреймворк.`
- Better: `Вона вирішила використовувати фреймворк.`

## Text Type Profiles

- General prose: natural, clear, contemporary Ukrainian; moderate paraphrase for Ukrainian syntax; preserve official names and translate descriptive titles when not protected.
- Literary fiction: preserve voice, register, rhythm, dialogue, imagery, irony, and ambiguity; transcribe ordinary personal names when appropriate for the reader unless the source context requires exact spelling.
- Literary non-fiction: polished editorial Ukrainian with author voice preserved; medium terminology strictness.
- Journalistic/publicistic: readable Ukrainian publicistic style; preserve facts, dates, attributions, and quotes.
- Scientific/academic: precise academic Ukrainian; preserve claims, uncertainty, citations, units, formulas, and terminology.
- Technical documentation: concise technical Ukrainian; preserve code, APIs, package names, filenames, command flags, environment variables, and product names.
- Business/legal-like: formal Ukrainian without unnecessary bureaucracy; preserve obligations, definitions, dates, amounts, and legal entity names.
- Educational: clear explanatory Ukrainian; translate descriptive headings and learning objectives.
- Marketing: idiomatic Ukrainian marketing copy without invented claims, false urgency, or exaggerated guarantees.
- Mixed/unknown: conservative general Ukrainian with technical and entity protections enabled.

## Terminology

Default policy: preserve technical precision, use established Ukrainian equivalents where natural, and avoid inconsistent switching between translation, transliteration, and preservation.

### Preserve

- API names, package names, library names, model names, product identifiers, environment variables, command names, flags, filenames, and code symbols;
- URLs, emails, usernames, issue IDs, document-control labels;
- registered brand and product names;
- legal company names unless a glossary or legal-localization setting overrides them.

### Translate

- `query parameters` -> `параметри запиту`;
- `regular expression` -> `регулярний вираз`;
- `footnote` -> `виноска`;
- `endnote` -> `кінцева виноска` or another glossary-pinned publishing term by context;
- `tracked changes` -> `виправлення` or `відстежені зміни` by UI/document context;
- `section break` -> `розрив розділу`;
- `merge cells` -> `об’єднати клітинки` or `об’єднання клітинок` by grammar;
- `table of contents` -> `зміст`;
- `data` -> `дані`.

### Transliterate, Transcribe, Or Preserve By Context

- `prompt` -> `промпт` in LLM/product context, `підказка` only when the source means a user hint;
- `token` -> `токен` in LLM/API/security context, `маркер` only when the source means a visible marker;
- `placeholder` -> `заповнювач` in general UI context, `плейсхолдер` in technical UI/LLM context when natural;
- `framework` -> `фреймворк`;
- `callback` -> `callback` for exact code/API reference, `зворотний виклик` or `колбек` in explanatory prose by context and glossary;
- `endpoint` -> preserve `endpoint` for exact API references; use `кінцева точка` or glossary-pinned `ендпоінт` in explanatory prose by project convention;
- `pipeline` -> `конвеєр`, `пайплайн`, or preserved product term by domain and glossary.

### Glossary Required

Use glossary-pinned forms for product UI terms, book series names, company-specific terminology, recurring technical terms, official legal names, institutions, repeated API concepts, and sensitive domain terminology.

### False Friends And Calques

The profile must explicitly guard against words and phrases that are plausible but wrong:

- `actual` -> usually `фактичний`, `реальний`, or `актуальний` by context, not automatically `актуальний`;
- `accurate` -> `точний`, not `акуратний` unless about neatness;
- `eventually` -> `зрештою`, `згодом`, `у підсумку`, not `евентуально`;
- `control` -> `керування`, `управління`, `перевірка`, or `контроль` by context;
- `regular` -> `звичайний`, `регулярний`, or `штатний` by context;
- `decade` -> `десятиліття`, while Ukrainian `декада` can mean a ten-day period;
- `magazine` -> `журнал`, while Ukrainian `магазин` means a shop;
- `participate` -> `брати участь`, not `приймати участь`;
- `during/over` -> often `протягом`, not `на протязі`;
- `is/constitutes` -> often `є`, not `являється`;
- `next/following` -> `наступний`, not `слідуючий`;
- `according to` -> `згідно з`, `відповідно до`, not `згідно` without the required form.

## Named Entities

- Personal names: transcribe ordinary names for Ukrainian readers in general and literary text when the name is not an exact identity record; preserve original spelling in citations, bibliography, legal identity, usernames, emails, code-owner contexts, and formal addresses.
- Ukrainian names from other-language sources: prefer standard Ukrainian forms where obvious and context-appropriate.
- Brands: preserve original brand spelling; do not translate registered brands.
- Products: preserve official names; translate generic descriptive categories around the name.
- Companies/legal names: preserve legal names and suffixes such as `LLC`, `Inc.`, `GmbH`, `B.V.` unless a legal-localization setting exists.
- Institutions/organizations: preserve official names when branded; translate descriptive names when no official branding is implied.
- Cities/countries: use established Ukrainian forms where they exist, for example `Netherlands` -> `Нідерланди`, `Germany` -> `Німеччина`, `Amsterdam` -> `Амстердам`.
- Streets/addresses: default to preserving exact address components when delivery/legal precision matters; translate descriptive parts only when safe.
- Titles: preserve official/branded titles; translate descriptive titles; future setting may use translated title with original in parentheses.
- Links/anchors: preserve URLs; translate ordinary prose anchors; protect product names, commands, IDs, and UI labels.
- Code/API/package names: always preserve exact spelling.

## Typography

- Quotes: use Ukrainian guillemets `«...»` for ordinary prose when typography normalization is safe.
- Nested quotes: use a consistent inner quote style only when the document adapter can preserve it safely.
- Dashes: use a spaced dash in ordinary prose where safe; preserve protected hyphens, ranges, IDs, command flags, filenames, and table spacing.
- Apostrophes: use Ukrainian apostrophe where ordinary Ukrainian spelling requires it; preserve apostrophes in names, code, and identifiers.
- Title capitalization: convert English Title Case to Ukrainian sentence-style capitalization unless preserving an official title or brand.
- Dates, units, numbers: preserve exact forms in legal/business/scientific data; localize only when policy allows it.
- Lists: preserve numbering, bullets, indentation, and hierarchy.
- Abbreviations: preserve technical abbreviations when protected; expand or translate descriptive abbreviations only when context clearly supports it.

## Protected Text Grammar

Protected English or code-like terms can make Ukrainian grammar awkward. The profile should prefer Ukrainian support nouns and sentence restructuring instead of modifying protected text.

- Use a Ukrainian generic noun around preserved foreign terms when inflection is needed: `модуль FastAPI`, `пакет requests`, `метод callback`, `змінна PATH`, `команда git commit`.
- Do not add Ukrainian endings inside inline code, API names, package names, URLs, commands, or protected markers.
- Use inflected Ukrainian borrowings only when the term is not protected and the form is natural: `фреймворку`, `токена`, `промпта`, `пайплайна`.
- If a preserved brand or API name needs case agreement, rewrite the sentence around it.
- Keep punctuation outside protected inline code where possible.

Examples:

- Awkward: `за допомогою framework`
- Better: `за допомогою фреймворку`
- Better when preserving official name: `за допомогою фреймворку FrameworkName`

- Awkward: `викличте callback`
- Better API reference: `викличте метод callback`
- Better explanatory prose: `викличте зворотний виклик`

## Source Pair Exceptions

- English -> Ukrainian: avoid English word order, mechanical possessives, article-like phrasing, literal phrasal verbs, false friends, and Title Case; preserve code/API/URL identifiers.
- Russian -> Ukrainian: translate meaning into standard Ukrainian, not by word replacement. Avoid Russian syntax calques, surzhyk, and false friends between close Slavic forms. Do not preserve Russian words unless they are names, citations, usernames, addresses, legal identities, or protected text.
- Mixed/auto -> Ukrainian: translate every human-language span into Ukrainian, including secondary languages. Preserve protected markers, code, URLs, placeholders, exact identifiers, and intentional names.
- Ukrainian source -> Ukrainian target: if detected, do not paraphrase unnecessarily; preserve document text except where normalization is explicitly part of a requested editing mode.
- Polish -> Ukrainian: avoid Polish diacritic transliteration as a substitute for translation; handle orthographic samples as letter tests.
- Dutch -> Ukrainian: split compounds by meaning and avoid Germanic noun stacking.
- German -> Ukrainian: resolve compound nouns, verb-final clauses, separable verbs, and modal scope before drafting Ukrainian.
- French/Spanish -> Ukrainian: avoid abstract-noun calques and false friends; preserve official accents in citations, brands, legal names, and identity contexts when required.

## Document Format Risks

- TXT: preserve blank-line paragraph flow, labels, pseudo-tables, and intentional spacing.
- DOCX: Ukrainian length and word order can disrupt run-level formatting; preserve tables, headers, footers, notes, comments, formulas, IDs, repeated spacing, and protected tokens without leaking markers.
- EPUB: preserve XHTML inline elements and spine order; captions, notes, and headings may need stricter translation than body prose.
- Future OCR/PDF: Ukrainian OCR language pack and Cyrillic-capable fonts are required before production-bound scanned/PDF output.
- Subtitles: Ukrainian may expand or contract compared with English or Russian; subtitle mode should prefer concise Ukrainian while preserving timing.
- CSV/TSV: preserve row/column count and machine-readable keys unless structured-value translation is explicitly enabled.

## User Controls

Current: user chooses target language only.

Future simple presets:

- `Natural Ukrainian`;
- `Technical Ukrainian`;
- `Literary Ukrainian`;
- `Preserve names`;
- `Transcribe names`;
- `Use glossary`.

Future advanced controls:

- technical terms: preserve, translate, transliterate/transcribe, glossary;
- personal names: preserve, transcribe, Ukrainian canonical form, original in parentheses;
- brands/products/companies: preserve, glossary;
- streets/addresses: preserve exact, transcribe, translate descriptive parts;
- titles: preserve, translate, translated with original in parentheses;
- text type override: general, technical, literary, business/legal-like, scientific, journalistic, marketing, mixed.

## Regression Samples

### Ordinary Prose

Source: `He made a decision after a high-level overview of the system.`

Expected: avoid `зробив рішення`; avoid awkward `високорівневий огляд` in general prose unless the context is explicitly technical.

Acceptable: `Він ухвалив рішення після загального огляду системи.`

Preferred general: `Він вирішив після загального огляду системи.`

### Russian-Calque Guard

Source: `Он принял участие в проекте на протяжении месяца.`

Expected: translate into standard Ukrainian; avoid `прийняв участь`, prefer `взяв участь`; use `проєкт`; use `протягом`.

Acceptable: `Він узяв участь у проєкті протягом місяця.`

### Literary

Source: `The room held its breath while the rain traced silver lines across the window.`

Expected: preserve imagery and rhythm; do not flatten to technical description.

Quality target: `Кімната ніби затамувала подих, поки дощ креслив срібні лінії на шибці.`

### Technical

Source: `Set the API endpoint and pass the placeholder token to the callback handler.`

Expected: preserve `API`; choose consistent terms for `endpoint`, `placeholder`, `token`, and `callback`; do not alter code-like identifiers.

Possible target: `Укажіть API endpoint і передайте токен-заповнювач обробнику callback.`

Alternative with more localized prose: `Укажіть кінцеву точку API й передайте токен-заповнювач обробнику зворотного виклику.`

The glossary should decide which version is preferred for the product.

### Business/Legal-Like

Source: `Acme B.V. shall deliver the materials by 15 March 2026.`

Expected: preserve `Acme B.V.`, date, obligation, and formal tone.

Acceptable: `Acme B.V. зобов’язується надати матеріали до 15 March 2026.`

If date localization is enabled: `Acme B.V. зобов’язується надати матеріали до 15 березня 2026 року.`

### Mixed-Language Labels

Source: `English + Russian: This section explains настройки профиля and API keys.`

Expected: translate all human-language spans into Ukrainian while preserving `API`.

Acceptable: `Англійська + російська: У цьому розділі пояснено налаштування профілю та ключі API.`

### Protected Text

Source: `Run git commit with ${MESSAGE} and open https://example.com/docs.`

Expected: preserve `git commit`, `${MESSAGE}`, and URL exactly.

Acceptable: `Виконайте команду git commit із ${MESSAGE} і відкрийте https://example.com/docs.`

## Acceptance Criteria

The Ukrainian profile is beta-ready when:

- the profile has no unresolved decisions;
- prompt tests cover the target-language profile and `en/ru/auto -> uk` source-pair profiles;
- cache policy signatures change when the Ukrainian profile version changes;
- regression samples cover ordinary prose, literary text, technical text, Russian-calque risk, mixed-language text, named entities, protected code/URLs/placeholders, DOCX, and EPUB;
- terminology and named-entity defaults are documented;
- text type behavior is documented;
- the target-language button, prompt language name, and language detection display are consistent.

The profile is production-ready when:

- beta feedback has no recurring unresolved Ukrainian quality class;
- common source-target pairs have examples and source-pair guidance;
- DOCX and EPUB samples preserve structure;
- glossary and named-entity settings are stored with the job or explicitly scoped out;
- cache keys include every policy field that changes translation output;
- failure modes and fallback behavior are documented.
