# EPUB Repair Pipeline Implementation Plan


**Goal:** Build a single EPUB repair pipeline that normalizes common legacy EPUB defects before planning, extraction, and assembly, while preserving strict rejection for unsafe input.

**Architecture:** Add a focused EPUB repair module that rewrites safe XML/XHTML defects at the whole-archive boundary and reports what it changed. Existing extractors and EPUB format adapter should consume repaired EPUB bytes so planning and assembly operate on the same normalized source. Keep generic XML parsing strict; EPUB-specific repair must never enable custom entity expansion.

**Tech Stack:** Python standard library (`zipfile`, `xml.etree.ElementTree`, `html.entities`, `re`), `unittest`, existing `translator_service.format_adapters.epub` and `translator_service.extractors`.

---

## File Structure

- Create `src/translator_service/format_adapters/epub_repair.py`
  - Own all EPUB-specific repair logic.
  - Expose `repair_epub_for_processing(content: bytes) -> RepairedEpub`.
  - Expose `normalize_epub_xml_part_for_xml(content: bytes) -> bytes` for XML parts parsed outside whole-archive repair during transition.
  - Include immutable report types for applied repair actions and warnings.
- Create `tests/test_epub_repair.py`
  - Cover repair module behavior independently from translation planning.
- Modify `src/translator_service/extractors.py`
  - Stop owning EPUB repair internals.
  - Call `repair_epub_for_processing()` once in `extract_epub_text_blocks()`.
  - Use the module-level XML-part normalizer only for EPUB XHTML bytes if needed by narrow helpers.
- Modify `src/translator_service/format_adapters/epub.py`
  - Call `repair_epub_for_processing()` once in `plan_epub_translation()` and `assemble_epub_content_from_block_translations()`.
  - Ensure assembled EPUB output is normalized even when there are no translated body replacements.
  - Use repaired bytes consistently for body, auxiliary metadata, NCX, and XHTML navigation/title processing.
- Modify `tests/test_extractors.py` and `tests/test_format_adapters.py`
  - Keep integration regression tests for legacy XHTML and NCX.
  - Add one real-world regression using the Kafka-style `DOCTYPE` + `&nbsp;` shape without depending on the local Downloads file.

---

### Task 1: Standalone EPUB Repair Module

**Files:**
- Create: `src/translator_service/format_adapters/epub_repair.py`
- Create: `tests/test_epub_repair.py`

- [ ] **Step 1: Write failing tests for safe XML/XHTML repairs**

Add tests that create small EPUB archives in memory and assert:

```python
from io import BytesIO
from zipfile import ZipFile

from translator_service.format_adapters.epub_repair import (
    repair_epub_for_processing,
)


def test_repairs_xhtml_and_ncx_doctype_and_named_entities():
    content = _make_epub(
        {
            "OPS/chapter.xhtml": """
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
              "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml">
              <body><p>One&nbsp;&mdash;&nbsp;two.</p></body>
            </html>
            """,
        },
        ncx_content="""
        <!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
         "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
        <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
          <docTitle><text>Old&nbsp;TOC</text></docTitle>
        </ncx>
        """,
    )

    repaired = repair_epub_for_processing(content)

    assert repaired.report.repaired is True
    assert any(action.kind == "strip_external_doctype" for action in repaired.report.actions)
    assert any(action.kind == "replace_named_entities" for action in repaired.report.actions)
    with ZipFile(BytesIO(repaired.content)) as epub:
        chapter = epub.read("OPS/chapter.xhtml")
        toc = epub.read("OPS/toc.ncx")
    assert b"<!DOCTYPE" not in chapter
    assert b"<!DOCTYPE" not in toc
    assert b"&nbsp;" not in chapter
    assert b"&nbsp;" not in toc
    assert b"&#160;" in chapter
    assert b"&#8212;" in chapter
```

- [ ] **Step 2: Write failing tests for unsafe input**

Add tests that assert custom entities and traversal filenames are rejected:

```python
import pytest

from translator_service.extractors import TextExtractionError


def test_rejects_custom_entity_definitions():
    content = _make_epub(
        {
            "OPS/chapter.xhtml": """
            <!DOCTYPE html [<!ENTITY injected "boom">]>
            <html xmlns="http://www.w3.org/1999/xhtml">
              <body><p>&injected;</p></body>
            </html>
            """,
        }
    )

    with pytest.raises(TextExtractionError, match="XML entities are not supported"):
        repair_epub_for_processing(content)


def test_rejects_epub_zip_path_traversal_members():
    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("../OPS/chapter.xhtml", "<html />")

    with pytest.raises(TextExtractionError, match="unsafe file path"):
        repair_epub_for_processing(archive.getvalue())
```

If this repository prefers `unittest`, write the same assertions with `unittest.TestCase` and `self.assertRaisesRegex`.

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_epub_repair
```

Expected: fail because `translator_service.format_adapters.epub_repair` does not exist.

- [ ] **Step 4: Implement repair module**

Implement:

```python
from __future__ import annotations

from dataclasses import dataclass
from html.entities import name2codepoint
from io import BytesIO
import re
from zipfile import BadZipFile, ZipFile

from translator_service.extractors import TextExtractionError, validate_archive_members


@dataclass(frozen=True)
class EpubRepairAction:
    kind: str
    file_name: str
    count: int = 1


@dataclass(frozen=True)
class EpubRepairReport:
    actions: tuple[EpubRepairAction, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def repaired(self) -> bool:
        return bool(self.actions)


@dataclass(frozen=True)
class RepairedEpub:
    content: bytes
    report: EpubRepairReport


def repair_epub_for_processing(content: bytes) -> RepairedEpub:
    try:
        source = BytesIO(content)
        target = BytesIO()
        actions: list[EpubRepairAction] = []
        with ZipFile(source) as source_epub:
            validate_archive_members(source_epub)
            _validate_epub_member_paths(source_epub)
            with ZipFile(target, "w") as target_epub:
                for item in source_epub.infolist():
                    data = source_epub.read(item)
                    if _is_repairable_epub_xml_part(item.filename):
                        data, item_actions = repair_epub_xml_part(
                            data,
                            file_name=item.filename,
                        )
                        actions.extend(item_actions)
                    target_epub.writestr(item, data)
        return RepairedEpub(
            content=target.getvalue(),
            report=EpubRepairReport(actions=tuple(actions)),
        )
    except BadZipFile as error:
        raise TextExtractionError("EPUB file does not contain readable book text") from error
```

Also implement:

- `repair_epub_xml_part(content: bytes, file_name: str) -> tuple[bytes, tuple[EpubRepairAction, ...]]`
- `normalize_epub_xml_part_for_xml(content: bytes) -> bytes`
- `_strip_external_doctype()`
- `_replace_html_named_entities()`
- `_validate_epub_member_paths()`
- `_is_repairable_epub_xml_part()` returning true for `.xhtml`, `.html`, `.htm`, `.ncx`

Rules:

- Reject any part containing `<!ENTITY`.
- Strip only simple external doctypes, not internal subsets.
- Preserve predefined XML entities: `amp`, `lt`, `gt`, `quot`, `apos`.
- Convert known HTML named entities to decimal numeric entities.
- Leave unknown named entities unchanged so strict XML parsing can reject them later.
- Reject member names that are absolute, contain `..`, contain backslashes, or end in `/..`.

- [ ] **Step 5: Run tests to verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_epub_repair
```

Expected: all tests pass.

---

### Task 2: Integrate Whole-Archive Repair Into EPUB Extraction and Planning

**Files:**
- Modify: `src/translator_service/extractors.py`
- Modify: `src/translator_service/format_adapters/epub.py`
- Modify: `tests/test_extractors.py`
- Modify: `tests/test_format_adapters.py`

- [ ] **Step 1: Write failing integration tests**

Ensure tests assert:

```python
def test_extracts_legacy_epub_xhtml_with_doctype_and_html_entities(self):
    content = _make_epub({
        "OPS/chapter.xhtml": """
        <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
          "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
        <html xmlns="http://www.w3.org/1999/xhtml">
          <body><p>First&nbsp;&mdash;&nbsp;second.</p></body>
        </html>
        """
    })

    self.assertEqual(extract_text_from_epub(content), "First — second.")
```

And:

```python
def test_plans_legacy_epub_ncx_with_external_doctype(self):
    plan = plan_epub_translation(
        content=_make_epub(
            {"OPS/chapter.xhtml": "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>First paragraph.</p></body></html>"},
            ncx_content=\"\"\"
            <!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
             "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <docTitle><text>Old Contents</text></docTitle>
            </ncx>
            \"\"\",
        ),
        max_fragment_chars=100,
    )

    self.assertIn("Old Contents", [block.text for unit in plan.units for block in unit.blocks])
```

- [ ] **Step 2: Run integration tests to verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_extractors.EpubExtractionTest.test_extracts_legacy_epub_xhtml_with_doctype_and_html_entities \
  tests.test_format_adapters.EpubFormatAdapterTest.test_plans_legacy_epub_ncx_with_external_doctype
```

Expected: fail until integration uses `repair_epub_for_processing()`.

- [ ] **Step 3: Integrate repair at EPUB boundaries**

In `extract_epub_text_blocks(content)`:

```python
repaired = repair_epub_for_processing(content)
with ZipFile(BytesIO(repaired.content)) as epub:
    ...
```

In `plan_epub_translation(content=...)`:

```python
repaired = repair_epub_for_processing(content)
content = repaired.content
```

Use the repaired bytes for both body block extraction and auxiliary block collection.

In `assemble_epub_content_from_block_translations(source_content=...)`:

```python
repaired = repair_epub_for_processing(source_content)
source_content = repaired.content
```

Then plan/replace from the repaired source.

- [ ] **Step 4: Remove duplicated repair internals from extractors**

Delete EPUB-specific regex/entity helpers from `extractors.py` after imports are moved to `epub_repair.py`. `extractors.py` should keep generic XML safety checks strict.

- [ ] **Step 5: Run integration tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_extractors tests.test_format_adapters
```

Expected: pass.

---

### Task 3: Normalize Output EPUB and Preserve Safety Guarantees

**Files:**
- Modify: `src/translator_service/format_adapters/epub.py`
- Modify: `tests/test_format_adapters.py`
- Modify: `tests/test_epub_repair.py`

- [ ] **Step 1: Write output normalization test**

Add or keep:

```python
def test_assembled_epub_normalizes_legacy_xhtml_output(self):
    source_content = _make_epub({
        "OPS/chapter.xhtml": """
        <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
          "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
        <html xmlns="http://www.w3.org/1999/xhtml">
          <body><p>First&nbsp;&mdash;&nbsp;second.</p></body>
        </html>
        """
    })

    content = assemble_epub_content_from_block_translations(
        source_content=source_content,
        translated_by_block_id={"epub:OPS/chapter.xhtml:0": "Первый — второй."},
    )

    with ZipFile(BytesIO(content)) as epub:
        chapter = epub.read("OPS/chapter.xhtml")
    self.assertNotIn(b"<!DOCTYPE", chapter)
    self.assertNotIn(b"&nbsp;", chapter)
    self.assertEqual(extract_text_from_epub(content), "Первый — второй.")
```

- [ ] **Step 2: Write tests for unchanged binary resources**

Add `tests/test_epub_repair.py` test:

```python
def test_repair_preserves_binary_resources():
    content = _make_epub({"OPS/chapter.xhtml": "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>Text</p></body></html>"})
    # Include image bytes in the helper or append them directly.
    repaired = repair_epub_for_processing(content)
    with ZipFile(BytesIO(repaired.content)) as epub:
        assert epub.read("OPS/image.png") == b"\\x89PNG\\r\\n\\x1a\\n"
```

- [ ] **Step 3: Implement output normalization via repaired source**

Once Task 2 repairs `source_content` before assembly, output normalization should already happen because all XHTML/NCX bytes entering replacement are repaired. Keep the explicit NCX normalization branch only if tests prove NCX can bypass whole-archive repair.

- [ ] **Step 4: Run safety and output tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_epub_repair tests.test_format_adapters
```

Expected: pass.

---

### Task 4: Realistic Regression and Verification

**Files:**
- Modify: `tests/test_epub_repair.py`
- Modify: `tests/test_format_adapters.py` if needed.

- [ ] **Step 1: Add a realistic Kafka-shaped fixture helper**

Create an in-memory EPUB with:

- `mimetype`
- `META-INF/container.xml`
- `OPS/content.opf`
- `OPS/toc.ncx` with external NCX doctype
- 2 XHTML files with XHTML 1.1 doctype and `&nbsp;`
- OPF metadata language intentionally mismatched, e.g. `nl`, to prove repair does not silently change source metadata during planning

- [ ] **Step 2: Add realistic regression test**

Assert:

```python
plan = plan_epub_translation(content=fixture, max_fragment_chars=4000)
self.assertGreater(plan.fragment_count, 0)
self.assertIn("Amerika", [block.text for unit in plan.units for block in unit.blocks])
```

Then assemble with `target_language="ru"` and assert:

```python
with ZipFile(BytesIO(output)) as epub:
    self.assertNotIn(b"<!DOCTYPE", epub.read("OPS/Text/chapter.xhtml"))
    self.assertNotIn(b"&nbsp;", epub.read("OPS/Text/chapter.xhtml"))
    self.assertNotIn(b"<!DOCTYPE", epub.read("OPS/toc.ncx"))
```

- [ ] **Step 3: Run focused suites**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_epub_repair \
  tests.test_extractors \
  tests.test_format_adapters \
  tests.test_order_estimates \
  tests.test_translation_runner
```

Expected: pass.

- [ ] **Step 4: Run compile verification**

Run:

```bash
/bin/zsh -lc "PYTHONPATH=src python3 -m compileall src"
```

Expected: exit 0.

- [ ] **Step 5: Document known unrelated full-suite failures**

If `PYTHONPATH=src python3 -m unittest discover -s tests` still fails in TXT partial assembly tests, do not fix them in this EPUB task. Record them as unrelated existing failures:

- `test_persistent_txt_cancellation_returns_partial_result`
- `test_assembles_partial_txt_with_pending_segments_in_source_language`

---

## Agent Execution Notes

- Execute tasks sequentially, not in parallel. Tasks touch overlapping EPUB files.
- Worker 1 owns Task 1 only: `epub_repair.py` and `tests/test_epub_repair.py`.
- Worker 2 owns Task 2 only after Task 1 is reviewed.
- Worker 3 owns Task 3 only after Task 2 is reviewed.
- Worker 4 owns Task 4 only after Task 3 is reviewed.
- Agents are not alone in the codebase. They must not revert existing user changes or unrelated dirty files.
- Existing dirty worktree includes admin/bot/persistent changes. Ignore those unless they block EPUB tests.
