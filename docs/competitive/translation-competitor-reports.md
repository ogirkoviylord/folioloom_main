# Translation Competitor Reports

This file stores bounded competitive QA reports for services adjacent to
FolioLoom: book/document translators, EPUB/DOCX/TXT translation tools, and
format-preserving AI translation products.

Use this file as competitive evidence and product-quality context. It is not a
release-readiness document, a product decision log, a legal/privacy document or
a universal benchmark.

Rules for future entries:

- Keep evidence short; do not paste long raw book/document excerpts.
- Separate confirmed facts from assumptions and Unknown/TBD items.
- Do not claim FolioLoom is production-ready or release-ready from competitor
  evidence.
- Do not claim universal competitor inferiority from one case.
- Record file format, source/target language, review depth and tools used.
- If a future entry implies product scope, create a separate scoped issue or
  architecture review before implementation.

## 2026-06-08 - BookTranslator.app Russian EPUB QA

Status: competitive QA evidence, not a product decision and not release
readiness evidence.

### Summary

This entry records a bounded comparison of a BookTranslator.app Russian EPUB
target-only output against the original `Amerika` EPUB source.

Verdict: **NEEDS REVIEW** for end-to-end EPUB translation quality.

BookTranslator.app preserved the broad source EPUB structure: the translated
file kept the same 11 XHTML spine documents and the same total extracted block
count as the source. Many sampled Russian passages are readable. However, the
output is not reader-ready because it contains at least one untranslated German
paragraph, one duplicated/replaced final paragraph in chapter `Ein Asyl`, and
visible name/heading consistency defects.

### Scope

Original file:

- `/Users/yuriimedvediev/Downloads/Amerika - Franz Kafka - EPUB.epub`

Translated file:

- `/Users/yuriimedvediev/Downloads/Amerika - [Translated by BookTranslator.app].epub`

Competitor context from owner-provided screenshot:

- Provider: BookTranslator.app.
- File format: EPUB.
- Target language: Russian.
- Displayed file size: `229KB`.
- Displayed word count: `87 295 words`.
- Displayed price: `$4.99`.
- Displayed status: `Finished`.
- Displayed created time: `Jun 7, 2026 at 10:21 PM`.
- Displayed ended time: `Jun 8, 2026 at 2:07 AM`.
- Displayed time spent: `37s`.
- Owner observed a long queue wait before the short processing time.
- UI offered `Download Target-Only` and `Download Bilingual`; only the
  target-only file was reviewed in this entry.

Public competitor facts checked on 2026-06-08:

- BookTranslator.app pricing page describes a `Guest` pay-per-task flow
  starting at `$1.99`, with guest tasks up to `300,000` words and guest
  history auto-deleting after `7 days`:
  <https://www.booktranslator.app/pricing>.
- The same pricing page lists the `50,001 - 100,000` word guest price as
  `$4.99`, matching this screenshot's displayed price for an `87 295` word
  book.
- BookTranslator.app marketing states that it offers target-language-only and
  bilingual side-by-side output modes:
  <https://www.booktranslator.app/blog/booktranslator-vs-google-translate>.
- BookTranslator.app help/marketing pages describe broad file support,
  including EPUB, PDF, DOCX, TXT, MOBI, Markdown, HTML, subtitle and structured
  localization formats. This was not independently tested here.

Review depth:

- EPUB package/container inspection.
- OPF/TOC/spine inspection.
- ZIP integrity check.
- Local EPUBCheck validation.
- Full block-count parity scan using extracted XHTML text blocks.
- Residual source-language scan.
- Duplicate/omission scan for suspicious block-length and repeated-content
  patterns.
- Name/terminology variant scan.
- Short sampled semantic and fluency review.
- No full line-by-line literary edit.
- No bilingual output review because the bilingual file was not supplied.

### Confirmed Facts

- Both source and BookTranslator.app output passed ZIP integrity checks with
  `unzip -t`.
- Source archive size was `229,047` bytes; BookTranslator.app output was
  `957,182` bytes.
- Both files had 11 XHTML text documents in the OPF spine.
- Extracted block totals matched exactly: `1116` source blocks and `1116`
  target blocks.
- Extracted source text was about `550,107` chars; extracted target text was
  about `490,881` chars.
- Source OPF had `dc:language` set to `nl`, even though the book text is
  German.
- BookTranslator.app output changed `dc:language` to `ru`.
- BookTranslator.app output kept the same OPF UUID as the source.
- Source and translated files both failed local EPUBCheck with `110` errors.
- The EPUBCheck failures were the same broad class in both files: duplicate
  XHTML IDs and missing referenced `page.css`.
- The translated output changed the TOC labels into Russian in many places, but
  some TOC labels and body headings disagree.

### Key Findings

| Severity | Location | Problem | Evidence | Likely cause | Recommended action |
| --- | --- | --- | --- | --- | --- |
| Critical | `OEBPS/Text/TheVirtualLibrary002.xhtml`, block 57 | A whole paragraph remains in German inside the Russian output. | The translated block starts with `»Nun hat diese Brummer«...`. | Provider miss, failed block replacement or assembly fallback. | Reject as reader-ready; retranslate the block and add residual source-language detection. |
| Critical | `OEBPS/Text/TheVirtualLibrary008.xhtml`, final block | The source final paragraph is omitted and replaced by a repeated translation of the previous long paragraph. | Source final paragraph begins `In solchen Gedanken...`; target repeats the student's `Непременно...` passage. | Block mapping, retry merge or assembly defect. | Rebuild/retranslate the affected chapter and verify source/target block identity at chapter endings. |
| Major | Whole book | Character names and transliterations are inconsistent. | Variants found included `Росман`, `Россман`, `Росманн`, `Россманн`, plus `Робинсон` and `Робинзон`; typo `Дламарш` also appeared. | No glossary/name-normalization pass or weak cross-chapter memory. | Run a terminology/name pass and add glossary consistency checks before delivery. |
| Major | TOC/body headings | Several TOC labels disagree with body headings. | Examples: TOC `Путь к Рамзесу` vs body `Дорога в Рамсес`; TOC `Природный театр Оклахомы` vs body `Das Naturtheater von Oklahoma`. | TOC and body headings appear translated independently or not reconciled. | Add heading/TOC consistency QA and normalize title policy. |
| Major | EPUB package | The output remains EPUBCheck-invalid. | Local EPUBCheck reported `110` errors for the output. | Service preserves source package defects rather than repairing them. | Treat EPUBCheck as a delivery QA signal; decide whether to preserve, repair or report source-side EPUB defects. |
| Minor | Metadata | Output updates language to `ru` but keeps the source UUID. | Same `urn:uuid:59c82721-9368-49a1-8920-02c8b37b6235` in source and output. | Shallow OPF metadata update. | Generate a new identifier for the translated derivative, or record an intentional metadata policy. |

### Structure Metrics

| Metric | Original EPUB | BookTranslator.app output | Result |
| --- | ---: | ---: | --- |
| Archive size | 229,047 bytes | 957,182 bytes | Output is about 4.2x larger. |
| ZIP entries | 21 | 23 | Same content set plus directory entries. |
| XHTML text docs | 11 | 11 | Broad spine shape preserved. |
| Extracted text blocks | 1116 | 1116 | No broad block-count collapse. |
| Extracted text chars | 550,107 | 490,881 | Plausible target/source volume. |
| OPF language | `nl` | `ru` | Target language metadata updated. |
| OPF UUID | same source UUID | same source UUID | Identifier was not regenerated. |
| EPUBCheck | 110 errors | 110 errors | Source defects preserved, not repaired. |

### Manual Sample Notes

The sampled Russian prose is often understandable and tracks the German source
meaning at the paragraph level. It is closer to a usable machine-translation
draft than the incomplete BookBridge.world output recorded above.

However, the critical defects are not stylistic: untranslated source text,
duplicated/replaced content and name drift make the file unsafe to treat as a
finished book translation. A human editor could polish many passages, but the
pipeline first needs automated checks that catch missing, duplicated or
untranslated blocks.

### Translation Quality Assessment

This section focuses on the quality of the Russian translation itself, separate
from EPUB packaging and assembly defects.

Verdict for translated passages that are actually present: **usable as a rough
machine-translation draft, not reader-ready literary Russian**.

Approximate qualitative rating from sampled source/target checks:

- Meaning preservation in sampled non-broken blocks: about `6/10`.
- Russian readability as a draft: about `6/10`.
- Literary/editorial quality for a Kafka novel: about `4/10`.

Confirmed from sampled passages:

- Many paragraphs preserve the basic event sequence and factual meaning well
  enough for rough comprehension.
- The opening scene with Karl, the ship and the Statue of Liberty is broadly
  correct at the meaning level.
- Descriptive scenes such as the uncle's house, Pollunder's country house,
  hotel/work scenes and the Oklahoma theatre poster are generally
  understandable.
- Dialogue is usually intelligible, but often reads like direct machine
  translation rather than edited Russian prose.

Quality limitations:

- The Russian often sounds grammatical but not literary. It smooths Kafka's
  tension and long syntactic pressure into a more generic explanatory style.
- Some phrasing is awkward or unidiomatic, for example short sampled patterns
  such as `смеясь ему`, `он, о ком так пеклись` and `заявляйтесь`.
- Register is inconsistent: some passages are neutral literary Russian, while
  others feel bureaucratic, over-literal or conversational in the wrong place.
- The translation frequently preserves literal source order and phrasing where
  a human literary translator would reshape the sentence.
- Quotation style is inconsistent, mixing Russian and German-style marks in the
  delivered text.
- Character-name drift is a translation-quality problem as well as a QA
  problem, because it weakens continuity across chapters.

Interpretation:

- The translation is not random or hallucinated in the ordinary passages
  sampled. It often gives the reader a usable understanding of what happens.
- It is not good enough to sell or present as a finished literary translation
  without human review.
- The main competitive weakness is not only prose quality. The bigger issue is
  absence of quality gates that would stop delivery after untranslated,
  duplicated or name-inconsistent output.

Practical quality bar:

- For private rough reading: **partially usable**, if the reader tolerates
  machine prose and occasional serious defects.
- For beta-quality book translation UX: **needs review**, because the product
  should detect and report the defects automatically.
- For reader-ready or publication-like output: **fail without human edit and
  repair pass**.

### Competitive Interpretation

Confirmed:

- BookTranslator.app has a polished consumer workflow: history, guest status,
  pay-per-task pricing, target-only download and bilingual download.
- For this sample, the displayed guest price of `$4.99` aligns with the
  competitor's public pricing table for a 50,001-100,000 word task.
- The service preserved broad EPUB structure much better than the
  BookBridge.world sample.
- The service did not repair source EPUBCheck defects.
- The service did not consistently enforce clean target-language output or name
  consistency.

Assumptions:

- The observed gap between created time and ended time likely represents queue
  wait plus a short active processing run. The competitor's internal queue
  accounting is Unknown.
- The untranslated and duplicated blocks may come from provider output, retry
  merging, chunk mapping or EPUB assembly. The exact internal cause is Unknown.

Strategic implication:

- BookTranslator.app is a serious product/UX competitor on price, breadth of
  formats, target-only/bilingual output and low-friction guest checkout.
- The quality gap FolioLoom can exploit is not merely "better prose"; it is
  verifiable delivery quality: residual source-language checks, block
  duplicate/omission checks, TOC/body heading consistency, terminology/name
  normalization and honest queue-vs-processing time reporting.

This is not a claim that FolioLoom is release-ready or generally better across
all BookTranslator.app cases. It is evidence that this BookTranslator.app EPUB
output needs review for a concrete German-to-Russian book case.

### Suggested FolioLoom QA Gates

These are follow-up candidates, not approved implementation scope:

- Residual source-language detection per block.
- Source/target block-count parity plus suspicious block-length ratio checks.
- Adjacent duplicate/repeated translation detection.
- Chapter-ending source/target boundary check.
- TOC/body heading consistency check.
- Character-name and place-name glossary consistency scan.
- EPUB metadata policy check for `dc:language`, title and identifier.
- Queue elapsed time and active processing time displayed separately.
- Optional: competitor-style target-only and bilingual output comparison flow.

### Tools / Commands Used

- `unzip -t` for archive integrity.
- `epubcheck` for local EPUB validation.
- Ad hoc Python scripts using `zipfile`, `xml.etree.ElementTree` and
  `html.parser.HTMLParser`.
- Public web lookup of BookTranslator.app pricing and marketing/help pages.

### Unknown / TBD

- The bilingual BookTranslator.app output quality is Unknown.
- The competitor's model, prompts, chunking, retry behavior and assembly
  implementation are Unknown.
- Whether the queue delay observed here is typical is Unknown.
- Whether FolioLoom should implement each suggested QA gate requires separate
  issue-level scope, acceptance criteria and verification plan.

### Risks / Guardrails

- Do not treat one competitor sample as universal evidence of competitor
  quality.
- Do not paste long raw book excerpts into issues, PRs, docs or support notes.
- Do not treat this comparison as release readiness evidence for FolioLoom.
- Do not expand FolioLoom product scope from this report without a separate
  approved issue or architecture review.

## 2026-06-07 - Cross-Service Product Observations

Status: owner-observed competitive notes, not independently reproduced by this
agent and not release readiness evidence.

Confirmed from owner report:

- In the BookBridge.world flow, the owner observed that the account balance did
  not replenish.
- The owner tried one additional similar service; its translation job entered a
  queue and did not progress.
- The owner observed that most adjacent services in this niche appear to be
  implemented from the same template, with the visible differences mainly in
  color palette.

Unknown / TBD:

- The exact payment/balance failure cause is Unknown.
- The additional queued service name, queue duration, job size and final status
  are Unknown.
- Whether the repeated UI patterns come from a shared template, white-label
  product, copied implementation, or convergent design is Unknown.

Competitive interpretation:

- The niche is real and already has multiple adjacent products.
- The observed competitor weakness is not only translation quality; reliability
  of payment/balance accounting, job queue progress and delivery feedback also
  appears fragile.
- FolioLoom should treat balance/payment state, queue progress and stuck-job
  recovery as product trust surfaces, not just backend implementation details.

## 2026-06-07 - BookBridge.world Russian EPUB QA

Status: competitive QA evidence, not a product decision and not release
readiness evidence.

### Summary

This entry records a bounded comparison of a BookBridge.world Russian EPUB
output against the same original `Amerika` EPUB source used in the
BookTranslator.ai review.

Verdict: **FAIL** for end-to-end EPUB translation quality.

BookBridge.world produced a technically cleaner EPUB package than the previous
competitor case: the output passed EPUBCheck, kept an uncompressed `mimetype`
entry and set target language metadata to `ru`. However, the delivered file is
not a complete book translation. It contains only navigation plus one content
chapter, and that chapter is itself truncated mid-sentence.

### Scope

Original file:

- `/Users/yuriimedvediev/Downloads/Amerika - Franz Kafka - EPUB.epub`

Translated file:

- `/Users/yuriimedvediev/Downloads/translation_3e5e4f0f-36e0-4af0-8263-3b51371ed177.epub`

Competitor context from owner:

- Provider: BookBridge.world.
- Target language: Russian.
- Original file is the EPUB without `translation_...` in the name.

Review depth:

- EPUB package/container inspection.
- OPF/TOC/spine inspection.
- Residual source-language and wrapper-text scan.
- Duplicate/repeated paragraph scan.
- Short sample review of the available translated content.
- No full line-by-line literary edit because the output is incomplete.

### Confirmed Facts

- Both files passed ZIP integrity checks with `unzip -t`.
- `file` recognized both files as EPUB documents.
- BookBridge output passed local EPUBCheck with `0` fatals, `0` errors and
  `0` warnings.
- The original EPUB failed EPUBCheck with source-side errors, so EPUBCheck is
  not a parity signal for source quality in this case.
- Original archive size was about `224 KB`; BookBridge output was about `15 KB`.
- Original spine had 11 XHTML documents; BookBridge spine had 2 items:
  `nav.xhtml` and `chap_01.xhtml`.
- BookBridge had only one real content chapter in the spine.
- Original TOC had 11 content nav points; BookBridge `toc.ncx` had 1 nav point.
- Extracted translated text was about `22,015` chars versus about `550,127`
  source chars, roughly `4.0%` of the original book text volume.
- BookBridge `chap_01.xhtml` was about `21,987` chars versus about `64,051`
  chars in the original first chapter, roughly `34.3%` of chapter 1.
- BookBridge OPF had `dc:language` set to `ru`.
- BookBridge chapter XHTML declared `lang="ru"` and `xml:lang="ru"`.
- Obvious provider wrapper/commentary patterns were not found.
- No repeated long paragraphs were found in the BookBridge output.

### Key Findings

| Severity | Location | Problem | Evidence | Likely cause | Recommended action |
| --- | --- | --- | --- | --- | --- |
| Critical | Whole EPUB | The delivered file contains only a small fraction of the original book. | Extracted output text was about `4.0%` of source text volume. | Export/generation limit, failed multi-chapter processing, or incomplete job delivery. | Reject output as-is; rerun full-book translation and verify spine/TOC coverage. |
| Critical | TOC/spine | Almost all original chapters are absent. | Original TOC had 11 content nav points; BookBridge TOC had only `Der Heizer`. | Format assembly or scope selection failure. | Require chapter-count parity check before delivery. |
| Critical | `EPUB/chap_01.xhtml` | The only translated content chapter is truncated mid-sentence. | Last extracted text ended with `что Шубаль`. | Generation cutoff or failed write/assembly boundary. | Rebuild/retranslate chapter 1 and verify it ends at the correct source boundary. |
| Major | Navigation/headings | Title and chapter label remain untranslated or source-language. | OPF/nav title `Amerika`; chapter heading `Der Heizer`. | Metadata/title normalization missing. | Translate or intentionally preserve titles consistently and record policy. |
| Major | `EPUB/chap_01.xhtml` | Name/term drift appears even inside the partial chapter. | Variants included `Шубал` and `Шубаль`. | No glossary/terminology pass. | Normalize recurring names after full translation exists. |
| Minor | Sampled prose | Some available Russian prose is readable but has awkward literal or grammatical phrasing. | Short sample issues included `словно в внезапно` and `на этом посудине`. | Machine translation without editorial pass. | Human edit after completeness and structure blockers are fixed. |

### Structure Metrics

| Metric | Original EPUB | BookBridge output | Result |
| --- | ---: | ---: | --- |
| Archive size | ~224 KB | ~15 KB | Strong incompleteness signal. |
| ZIP entries | 21 | 8 | Output package is much smaller. |
| Spine XHTML docs/items | 11 | 2 | Only `nav` plus one chapter. |
| Real content chapters in output | 10+ source sections | 1 | Most book content absent. |
| TOC content nav points | 11 | 1 | Almost all navigation absent. |
| Extracted text chars | 550,127 | 22,015 | About `4.0%` of source. |
| First chapter text chars | 64,051 | 21,987 | About `34.3%` of source chapter. |
| EPUBCheck | Source has errors | Output clean | Output validity does not imply completeness. |

### Manual Sample Notes

Because the output is incomplete, manual style review is secondary.

Observed sample-level pattern:

- The beginning of chapter 1 broadly follows the source meaning.
- Some prose is readable enough for a machine translation draft.
- The output ends while still inside the early first-chapter dispute around
  Schubal.
- The rest of chapter 1 and all later book sections are missing, so the file is
  unusable as a book translation.

### Competitive Interpretation

Confirmed:

- BookBridge.world produced a valid EPUB container for this sample.
- It handled target-language metadata better than the earlier BookTranslator.ai
  sample.
- It failed the most important delivery criterion: complete translated book
  coverage.

Assumption:

- The failure may reflect a service limit, chunk/export bug or a UI/job flow
  that delivered only a preview/partial result. The exact cause is Unknown.

Strategic implication:

- BookBridge.world may look stronger on EPUB packaging and language metadata.
- It is weaker on this case than a complete book workflow requires because it
  returns an incomplete file without obvious in-file warning.
- FolioLoom should treat completeness checks as a first-class competitive gate:
  spine count, TOC count, per-chapter text coverage and end-boundary checks.

This is not a claim that FolioLoom is release-ready or generally better across
all BookBridge.world cases. It is evidence that this BookBridge.world EPUB
output failed a concrete end-to-end completeness QA case.

### Suggested FolioLoom QA Gates

These are follow-up candidates, not approved implementation scope:

- Source/target spine item parity check.
- TOC/navPoint coverage check.
- Per-chapter extracted-text coverage ratio check.
- Last-block/end-boundary check for each translated chapter.
- Detection of output that looks like preview/partial content without explicit
  partial-output metadata.
- Target metadata/title/headings consistency check.
- Terminology/name drift scan after full output exists.

### Tools / Commands Used

- `unzip -t` for archive integrity.
- `file` for basic OS-level file recognition.
- `epubcheck` for local EPUB validation.
- `python3 tools/epub_audit.py ... --out /tmp/folioloom_bookbridge_epub_audit`
- Ad hoc Python scripts using `zipfile`, `xml.etree.ElementTree` and
  `html.parser.HTMLParser`.

### Unknown / TBD

- Whether the BookBridge.world output was intended as a preview, partial sample
  or final paid/free result is Unknown from repository evidence.
- The competitor's internal model, prompts, limits and assembly pipeline are
  Unknown.
- Whether this failure reproduces across other BookBridge.world files is
  Unknown.
- Whether FolioLoom should add each suggested QA gate requires issue-level
  scope, acceptance criteria and verification plan.

### Risks / Guardrails

- Do not treat a valid EPUB package as proof of complete translation coverage.
- Do not paste long raw book excerpts into issues, PRs, docs or support notes.
- Do not claim universal competitor inferiority from one test case.
- Use this as competitive QA evidence and as input for future scoped issues.

## 2026-06-07 - BookTranslator.ai Russian EPUB QA

Status: competitive QA evidence, not a product decision and not release
readiness evidence.

### Summary

This entry records a bounded comparison of a BookTranslator.ai output against
its original EPUB source.

Verdict: **FAIL** for end-to-end EPUB translation quality.

BookTranslator.ai preserved the broad EPUB spine shape, but the translated file
contains critical assembly and translation defects: duplicated/reordered
content, untranslated German source text, mixed English/source fragments,
incorrect target-language metadata and inconsistent terminology/name handling.
The result should not be treated as a usable Russian book translation without a
repair/retranslation pass.

### Scope

Original file:

- `/Users/yuriimedvediev/Downloads/Amerika - Franz Kafka - EPUB.epub`

Translated file:

- `/Users/yuriimedvediev/Downloads/2026-06-07T192915816Z-Russian-1780851973532-Amerika - Franz Kafka - EPUB.epub`

Competitor context from owner-provided screenshots:

- Provider: BookTranslator.ai.
- Uploaded file: `Amerika - Franz Kafka - EPUB.epub`.
- Displayed token count: `157 368`.
- Pricing plan shown: Basic Translation at `$0.03 per 1000 tokens`, total
  `$6.99` due to minimum price.
- Progress UI showed `25 chunks` and `11 files`.

Review depth:

- EPUB package/container inspection.
- OPF/TOC/spine inspection.
- Residual source-language scan.
- Duplicate/repeated paragraph scan.
- Short aligned sample review across the beginning, middle and end.
- No full line-by-line literary edit.

### Confirmed Facts

- Both EPUB archives passed ZIP integrity checks with `unzip -t`.
- Both files contain 11 spine XHTML documents.
- No entire spine chapter was missing from the translated EPUB.
- The translated archive contains 25 ZIP entries versus 21 in the original; the
  extra entries are directory entries.
- The original `mimetype` entry is stored uncompressed; the translated
  `mimetype` entry is deflated.
- `file` recognized the original as an EPUB document but recognized the
  translated file only as ZIP data.
- The translated OPF title was changed to `Америка`.
- The translated OPF `dc:language` remained `nl` instead of Russian.
- The translated XHTML body files still declare `xml:lang="de"`.
- Provider commentary patterns such as `as an AI`, `OpenAI`, `BookTranslator`,
  `prompt` and similar obvious wrapper text were not found in the translated
  text scan.

### Key Findings

| Severity | Location | Problem | Evidence | Likely cause | Recommended action |
| --- | --- | --- | --- | --- | --- |
| Critical | `OEBPS/Text/TheVirtualLibrary008.xhtml` | Untranslated German source text remains in the Russian EPUB. | Short scan hit: `Zuruck, ihr Kinder` / `Polizeimann` section remained source-language text. | Provider output or chunk assembly failure. | Rebuild/retranslate chapter 8, then run residual source-language scan. |
| Critical | `OEBPS/Text/TheVirtualLibrary008.xhtml` | Scene content is duplicated/reordered in multiple Russian variants. | `Как тебя зовут?` appeared 9 times in suspiciously repeated blocks. | Chunk duplication or work-unit assembly failure. | Reassemble chapter 8 from aligned source blocks before any human edit. |
| Critical | `OEBPS/Text/TheVirtualLibrary004.xhtml` | A chapter-start section was inserted again later in the same chapter. | Chapter title `Загородный дом под Нью-Йорком` appeared twice in body extraction. | Chunk boundary or assembly duplication. | Remove duplicated section and verify paragraph-to-source alignment. |
| Major | `OEBPS/Text/TheVirtualLibrary008.xhtml` | Mixed English/source residue appears inside Russian prose. | Short scan hits included `Automobil`, `and stomped foot`, `against`. | Provider contamination or incomplete cleanup. | Re-translate affected blocks and scan for non-target-language residue. |
| Major | EPUB metadata/package | Target-language metadata was not updated and EPUB packaging is weaker than the original. | `dc:language` stayed `nl`; translated `mimetype` entry was compressed. | Format repair gap. | Set target language metadata to `ru`; package EPUB with uncompressed first `mimetype`. |
| Major | Headings/navigation/body | Chapter heading variants are inconsistent. | TOC/body variants include `Путь к Рамзесу` vs `Путь в Рамзес`, `Приют` vs `Убежище`. | No title/heading normalization pass. | Normalize TOC labels and body headings. |
| Major | Whole book | Recurring names and terms drift. | Counts showed variants such as `Робинсон`/`Робинзон`, `Россман`/`Россманн`, `Деламарш`/`Деламарше`, `Оксидентал`/`Оксиденталь`. | No glossary/terminology pass. | Run terminology normalization after structural repair. |
| Minor | Sampled prose outside broken chapters | Some sampled paragraphs preserve meaning but read mechanically or have typography issues. | Examples include rough hyphen/quote handling and literal phrasing. | Machine translation style, no editorial pass. | Human edit after structural blockers are fixed. |

### Chapter / Structure Metrics

Extracted character ratios showed abnormal growth in specific translated
chapters:

| Spine file | Original chars | Translation chars | Ratio | Notes |
| --- | ---: | ---: | ---: | --- |
| `TheVirtualLibrary002.xhtml` | 64,051 | 56,225 | 0.88 | No major blocker found in sampled text. |
| `TheVirtualLibrary003.xhtml` | 30,300 | 26,805 | 0.88 | No major blocker found in sampled text. |
| `TheVirtualLibrary004.xhtml` | 73,657 | 85,878 | 1.17 | Duplicated chapter-start section. |
| `TheVirtualLibrary005.xhtml` | 59,110 | 51,352 | 0.87 | Heading variant risk. |
| `TheVirtualLibrary006.xhtml` | 42,578 | 37,297 | 0.88 | Terminology variant risk. |
| `TheVirtualLibrary007.xhtml` | 86,618 | 86,736 | 1.00 | Paragraph count increased. |
| `TheVirtualLibrary008.xhtml` | 115,436 | 155,522 | 1.35 | Critical duplication/residual-source blocker. |
| `TheVirtualLibrary009.xhtml` | 44,453 | 38,986 | 0.88 | Sample looked mostly aligned. |
| `TheVirtualLibrary010.xhtml` | 22,608 | 19,631 | 0.87 | No major blocker found in sampled text. |
| `TheVirtualLibrary011.xhtml` | 11,214 | 9,995 | 0.89 | Sample looked mostly aligned. |

Paragraph/tag extraction also showed suspicious expansion:

- Chapter 4: original 202 raw `<p>` tags, translation 288.
- Chapter 8: original 279 raw `<p>` tags, translation 588.

### Manual Sample Notes

Short aligned samples from the beginning and end often preserved broad meaning.
That does not rescue the file because the structural defects are critical.

Observed sample-level pattern:

- Some ordinary prose in chapters 2, 3, 5, 6, 9 and 11 was mostly aligned.
- Russian style was often literal and would benefit from an editorial pass.
- The decisive failures were not subjective style problems; they were
  objective final-file defects: untranslated source text, duplicated content,
  mixed-language fragments and incorrect package metadata.

### Competitive Interpretation

Confirmed:

- BookTranslator.ai has a polished upload/payment/progress flow.
- The competitor advertises a broad target-language selection and presents a
  simple purchase path.
- On this EPUB case, the delivered file failed final-output quality gates that
  matter for book translation.

Assumption:

- The main failure mode is likely chunk assembly or provider-output cleanup,
  not the inability of the model to translate every individual paragraph.

Strategic implication:

- The competitor may win first impressions with language coverage and checkout
  simplicity.
- FolioLoom can differentiate on trust: final EPUB validity, structure
  preservation, residual-source-language scans, duplicate-block scans, metadata
  repair and terminology consistency before delivering the file.

This is not a claim that FolioLoom is release-ready or generally better across
all languages. It is evidence that a direct competitor failed a concrete
end-to-end EPUB QA case.

### Suggested FolioLoom QA Gates

These are follow-up candidates, not approved implementation scope:

- Residual source-language scan for translated output.
- Duplicate paragraph/block scan, especially per EPUB spine item.
- OPF language metadata check for target language.
- XHTML `xml:lang` target-language check where safe.
- EPUB packaging check for uncompressed first `mimetype`.
- TOC/body heading consistency check.
- Name/terminology drift scan for recurring entities.
- Provider-wrapper/commentary scan.
- Before/after reader evidence for suspicious chapters.

### Tools / Commands Used

- `unzip -t` for archive integrity.
- `file` for basic OS-level file recognition.
- `python3 tools/epub_audit.py ... --out /tmp/folioloom_competitor_epub_audit`
- Ad hoc Python scripts using `zipfile`, `xml.etree.ElementTree` and
  `html.parser.HTMLParser`.
- A subagent using the `translation-quality-review` skill from branch
  `codex/full-translation-diagnostic-archive`.

### Unknown / TBD

- EPUBCheck was not run on the competitor output.
- The competitor's internal model, prompts, chunking and assembly pipeline are
  Unknown.
- Whether this failure reproduces across other BookTranslator.ai files is
  Unknown.
- Whether FolioLoom should add each suggested QA gate requires issue-level
  scope, acceptance criteria and verification plan.
- Public marketing/positioning claims based on this evidence are TBD and should
  remain careful unless more competitor cases are reviewed.

### Risks / Guardrails

- Do not paste long raw book excerpts into issues, PRs, docs or support notes.
- Do not treat this report as legal/privacy/release readiness evidence.
- Do not claim universal competitor inferiority from one test case.
- Do not expand product scope or language support solely from this report.
- Use this as competitive QA evidence and as input for future scoped issues.
