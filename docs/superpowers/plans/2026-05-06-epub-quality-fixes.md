# EPUB Quality Fixes Implementation Plan


**Goal:** Make EPUB translation and partial output match real reader expectations: translate readable book content first, update EPUB metadata/navigation, and avoid obvious language-context failures.

**Architecture:** Keep the existing EPUB adapter in `src/translator_service/translation_runner.py`, but split its behavior into readable body units, auxiliary metadata/navigation units, and ignored noise. Body units drive estimate/progress/partial output; metadata/navigation are updated after body translation and do not consume visible progress.

**Tech Stack:** Python standard `zipfile` and `xml.etree.ElementTree`, existing `TranslationProgress`, `RecordingTranslator` tests, existing synthetic EPUB fixture helper in `tests/test_translation_runner.py`.

---

### Task 1: Regression Tests For Partial Body Order

**Files:**
- Modify: `tests/test_translation_runner.py`
- Modify: `src/translator_service/translation_runner.py`

- [ ] **Step 1: Write failing tests**

Add tests proving that navigation/noise does not consume the first partial units:

```python
def test_cancelled_epub_translation_skips_navigation_and_noise_for_partial_body(self):
    translator = RecordingTranslator()
    token = CancellationToken()
    content = _make_epub(
        {
            "OPS/nav.xhtml": """
            <html xmlns="http://www.w3.org/1999/xhtml">
              <body>
                <nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops">
                  <h1>Contents</h1>
                  <ol><li>Chapter 1</li><li>Chapter 2</li></ol>
                </nav>
              </body>
            </html>
            """,
            "OPS/chapter1.xhtml": """
            <html xmlns="http://www.w3.org/1999/xhtml">
              <body>
                <h1>Chapter 1</h1>
                <p>* * *</p>
                <p>First real paragraph of the book.</p>
                <p>Second real paragraph of the book.</p>
              </body>
            </html>
            """,
        },
        spine=["OPS/nav.xhtml", "OPS/chapter1.xhtml"],
    )

    def cancel_after_first(progress: TranslationProgress) -> None:
        if progress == (1, 2):
            token.cancel()

    result = translate_epub_document(
        file_name="book.epub",
        content=content,
        source_language="en",
        target_language="uk",
        translator=translator,
        max_fragment_chars=40,
        progress_callback=cancel_after_first,
        cancellation_token=token,
    )

    self.assertTrue(result.is_partial)
    self.assertEqual(result.fragment_count, 1)
    text = extract_text_from_epub(result.content)
    self.assertIn("[uk] First real paragraph of the book.", text)
    self.assertIn("Second real paragraph of the book.", text)
    self.assertNotIn("[uk] Contents", text)
    self.assertNotIn("[uk] * * *", text)
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_translation_runner.TranslationRunnerTest.test_cancelled_epub_translation_skips_navigation_and_noise_for_partial_body
```

Expected: fail because navigation/noise are still counted as normal EPUB text units.

- [ ] **Step 3: Implement EPUB block role classification**

Add an internal role field to `_EpubTextBlock`, classify navigation and noise, and feed only translatable body/heading blocks into `_group_epub_blocks`.

- [ ] **Step 4: Run the test again**

Run the same command. Expected: pass.

### Task 2: Metadata, TOC, And HTML Title Updates

**Files:**
- Modify: `tests/test_translation_runner.py`
- Modify: `src/translator_service/translation_runner.py`

- [ ] **Step 1: Write failing tests**

Add a synthetic EPUB with `dc:title`, `dc:description`, `dc:language`, `toc.ncx`, and HTML `<title>`. Assert that the translated EPUB updates user-facing metadata and navigation but preserves IDs/hrefs.

- [ ] **Step 2: Run the failing test**

Run the targeted unittest for the new metadata test. Expected: fail because metadata and TOC currently remain in the original language.

- [ ] **Step 3: Implement auxiliary EPUB text translation**

Translate metadata/navigation strings after body translation. Update only readable strings: OPF title/description/language, NCX `text`, EPUB3 nav text, and HTML title. Preserve UUID, dates, authors, hrefs, IDs, image references, and media types.

- [ ] **Step 4: Run the metadata tests**

Expected: pass and existing EPUB tests still pass.

### Task 3: Secondary Languages And Narrator Context

**Files:**
- Modify: `tests/test_translation_runner.py`
- Modify: `src/translator_service/translation_runner.py`
- Modify: `src/translator_service/deepseek_client.py`

- [ ] **Step 1: Write failing tests**

Assert that EPUB translation batches include source-language hints for detected secondary-language blocks when `source_language="auto"` and that prompts include a rule to preserve narrator person/gender/number.

- [ ] **Step 2: Run targeted tests**

Expected: fail if the prompt lacks the explicit narrator-consistency rule or if secondary language hints are missing.

- [ ] **Step 3: Implement prompt/context update**

Keep the model instruction provider-agnostic to users, but add internal instructions to translate secondary-language passages semantically and never transliterate them unless explicitly requested.

- [ ] **Step 4: Run all translation tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_translation_runner
```

Expected: pass.

### Task 4: Full Verification

**Files:**
- No new files unless tests expose a scoped helper need.

- [ ] **Step 1: Run full unit test suite**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex_pycache_dev PYTHONPATH=src python3 -m compileall src
```

Expected: compile succeeds.
