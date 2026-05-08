# My Books Detail UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a beautiful and practical `My Books` history UI with paginated book lists, human-readable book titles, and a detail screen for each translation job.

**Architecture:** Telegram remains a renderer only. `BotTranslationService` owns history lookup, title selection, ownership checks, and result retrieval; `bot.messages` owns localized list/detail text; `bot.runtime` owns inline keyboards and callbacks. The list uses book-title buttons such as `📘 Ave Maria`; the detail screen is a polished book card, not a debug dump, and owns actions such as download, continue later, retry later, and back to list.

**Tech Stack:** Python 3.13, aiogram inline keyboards/callback queries, SQLite persistent job store, local object storage, EPUB/DOCX metadata parsing with standard-library ZIP/XML where possible, `unittest`.

---

## UX Target

The list should look like this:

```text
📚 Мои книги

1. Аве Мария
   EPUB · Русский → Украинский · готово · можно скачать

2. Call Me by Your Name
   EPUB · English → Українська · готово · можно скачать

3. Краш-тест документа
   DOCX · English → Русский · частичный результат · можно скачать

Страница 1/4
```

The inline buttons under the list should be title-based, not number-based:

```text
[📘 Аве Мария]
[📘 Call Me by Your Name]
[📄 Краш-тест документа]
[← Назад] [Вперед →]
[🏠 Главное меню]
```

Pressing a title opens a visually tidy book card. This first implementation is text-based, but it should already be formatted as a product card so a cover thumbnail can be added later without redesigning the flow:

```text
📘 Аве Мария

EPUB · Русский → Украинский

Статус: готово
Прогресс: 100%
Результат: доступен

Файл: veyer_endi_proekt_ave_mariya.epub
```

Detail buttons:

```text
[⬇️ Скачать перевод]
[← К списку]
[🏠 Главное меню]
```

No list button should say `Open 1`, `Open 2`, `Download 1`, or `Download 2`. Numeric indexes may stay in message text for scanability, but buttons should use readable book titles.

---

## File Structure

- Modify `src/translator_service/document_titles.py`: create title extraction helpers for EPUB, DOCX, TXT fallback, and title shortening for Telegram buttons.
- Modify `src/translator_service/persistent_jobs.py`: add display-title storage, count, and offset pagination for user jobs.
- Modify `src/translator_service/bot_translation_service.py`: expose paginated book pages, single-book lookup, title fields, and specific result download with owner validation.
- Modify `src/translator_service/bot/messages.py`: add localized list/detail builders and button labels.
- Modify `src/translator_service/bot/runtime.py`: add callbacks for list pages, book detail pages, and downloads.
- Modify `tests/test_document_titles.py`: prove metadata title extraction and fallbacks.
- Modify `tests/test_persistent_jobs.py`: prove display-title persistence and pagination/count ordering.
- Modify `tests/test_bot_translation_service.py`: prove book page/detail/result access, display titles, and owner checks.
- Modify `tests/test_bot_messages.py`: prove localized page/detail text with titles.
- Modify `tests/test_bot_runtime.py`: prove title-button callback payloads and keyboard shapes.
- Modify `docs/superpowers/specs/2026-05-03-deepseek-document-telegram-bot-design.md`: record the implemented `My Books` UX.

---

### Task 1: Book Display Title Extraction

**Files:**
- Create: `src/translator_service/document_titles.py`
- Test: `tests/test_document_titles.py`

- [ ] **Step 1: Write failing title extraction tests**

Create `tests/test_document_titles.py`:

```python
import io
import unittest
import zipfile

from translator_service.document_titles import (
    build_display_title,
    shorten_button_title,
)


class DocumentTitleTest(unittest.TestCase):
    def test_uses_epub_dc_title_when_available(self):
        content = _epub_with_title("Ave Maria")

        self.assertEqual(
            build_display_title(file_name="raw-file-name.epub", content=content),
            "Ave Maria",
        )

    def test_uses_docx_core_title_when_available(self):
        content = _docx_with_title("Stress Test Document")

        self.assertEqual(
            build_display_title(file_name="stress.docx", content=content),
            "Stress Test Document",
        )

    def test_falls_back_to_clean_file_stem(self):
        self.assertEqual(
            build_display_title(file_name="veyer_endi_proekt_ave_mariya.epub", content=b"not a zip"),
            "veyer endi proekt ave mariya",
        )

    def test_shortens_long_button_title(self):
        self.assertEqual(
            shorten_button_title("A" * 80, max_length=30),
            "A" * 29 + "…",
        )


def _epub_with_title(title: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
              </rootfiles>
            </container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0"?>
            <package xmlns:dc="http://purl.org/dc/elements/1.1/">
              <metadata><dc:title>{title}</dc:title></metadata>
            </package>""",
        )
    return buffer.getvalue()


def _docx_with_title(title: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "docProps/core.xml",
            f"""<?xml version="1.0"?>
            <cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                xmlns:dc="http://purl.org/dc/elements/1.1/">
              <dc:title>{title}</dc:title>
            </cp:coreProperties>""",
        )
    return buffer.getvalue()
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_document_titles
```

Expected: fail because `translator_service.document_titles` does not exist.

- [ ] **Step 3: Implement title extraction**

Create `src/translator_service/document_titles.py`:

```python
from pathlib import PurePath
import re
import xml.etree.ElementTree as ET
import zipfile


def build_display_title(*, file_name: str, content: bytes) -> str:
    suffix = PurePath(file_name).suffix.lower()
    if suffix == ".epub":
        title = _epub_title(content)
        if title:
            return title
    if suffix == ".docx":
        title = _docx_title(content)
        if title:
            return title
    return _file_stem_title(file_name)


def shorten_button_title(title: str, *, max_length: int = 38) -> str:
    normalized = " ".join(title.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "…"


def _epub_title(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(_bytes_reader(content)) as archive:
            opf_path = _epub_opf_path(archive)
            if not opf_path:
                return None
            return _xml_title(archive.read(opf_path))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None


def _docx_title(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(_bytes_reader(content)) as archive:
            return _xml_title(archive.read("docProps/core.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None


def _epub_opf_path(archive: zipfile.ZipFile) -> str | None:
    root = ET.fromstring(archive.read("META-INF/container.xml"))
    for element in root.iter():
        if element.tag.endswith("rootfile"):
            return element.attrib.get("full-path")
    return None


def _xml_title(xml_bytes: bytes) -> str | None:
    root = ET.fromstring(xml_bytes)
    for element in root.iter():
        if element.tag.endswith("title") and element.text:
            title = " ".join(element.text.split())
            if title:
                return title
    return None


def _file_stem_title(file_name: str) -> str:
    stem = PurePath(file_name).stem
    cleaned = re.sub(r"[_\\-]+", " ", stem)
    cleaned = re.sub(r"\\s+", " ", cleaned).strip()
    return cleaned or "Untitled"


def _bytes_reader(content: bytes):
    from io import BytesIO

    return BytesIO(content)
```

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_document_titles
```

Expected: all document-title tests pass.

---

### Task 2: Persistent Job Pagination and Display Titles

**Files:**
- Modify: `src/translator_service/persistent_jobs.py`
- Test: `tests/test_persistent_jobs.py`

- [ ] **Step 1: Write failing pagination/title tests**

Add tests proving display title persistence, newest-first pagination, and total count:

```python
def test_create_job_persists_display_title(self):
    store = SQLiteTranslationJobStore(":memory:")
    self.addCleanup(store.close)

    job = store.create_job(
        order_id="order-1",
        user_id="telegram:42",
        file_id="file-1",
        file_name="raw.epub",
        display_title="Ave Maria",
        document_kind="epub",
        source_language="ru",
        target_language="uk",
        adapter_version="epub-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        source_object_key="original/raw.epub",
    )

    self.assertEqual(job.display_title, "Ave Maria")


def test_lists_jobs_for_user_with_offset_and_limit(self):
    store = SQLiteTranslationJobStore(":memory:")
    self.addCleanup(store.close)
    created = [
        store.create_job(
            order_id=f"order-{index}",
            user_id="telegram:42",
            file_id=f"file-{index}",
            file_name=f"book-{index}.txt",
            display_title=f"Book {index}",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key=f"original/book-{index}.txt",
        )
        for index in range(7)
    ]

    page = store.list_jobs_for_user("telegram:42", limit=3, offset=3)

    self.assertEqual([job.id for job in page], [created[3].id, created[2].id, created[1].id])


def test_counts_jobs_for_user(self):
    store = SQLiteTranslationJobStore(":memory:")
    self.addCleanup(store.close)
    for index in range(4):
        store.create_job(
            order_id=f"order-{index}",
            user_id="telegram:42",
            file_id=f"file-{index}",
            file_name=f"book-{index}.txt",
            display_title=f"Book {index}",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key=f"original/book-{index}.txt",
        )
    store.create_job(
        order_id="order-other",
        user_id="telegram:100",
        file_id="file-other",
        file_name="other.txt",
        display_title="Other",
        document_kind="txt",
        source_language="en",
        target_language="ru",
        adapter_version="txt-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        source_object_key="original/other.txt",
    )

    self.assertEqual(store.count_jobs_for_user("telegram:42"), 4)
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs
```

Expected: fail because `display_title`, `offset`, and `count_jobs_for_user` do not exist yet.

- [ ] **Step 3: Add `display_title` to persistent job schema**

Add `display_title: str` to `PersistentTranslationJob`.

Update schema creation to include:

```sql
display_title TEXT NOT NULL DEFAULT ''
```

Update `create_job` signature:

```python
display_title: str | None = None,
```

Store `display_title or file_name`.

Update `_job_from_row` to read `display_title`.

If schema migrations already exist, add an idempotent migration:

```python
def _ensure_display_title_column(self) -> None:
    columns = {
        row["name"]
        for row in self._connection.execute("PRAGMA table_info(translation_jobs)").fetchall()
    }
    if "display_title" not in columns:
        self._connection.execute(
            "ALTER TABLE translation_jobs ADD COLUMN display_title TEXT NOT NULL DEFAULT ''"
        )
        self._connection.execute(
            "UPDATE translation_jobs SET display_title = file_name WHERE display_title = ''"
        )
```

- [ ] **Step 4: Implement pagination/count**

Update `list_jobs_for_user`:

```python
def list_jobs_for_user(
    self,
    user_id: str,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[PersistentTranslationJob]:
    rows = self._connection.execute(
        """
        SELECT * FROM translation_jobs
        WHERE user_id = ?
        ORDER BY datetime(updated_at) DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, max(1, limit), max(0, offset)),
    ).fetchall()
    return [_job_from_row(row) for row in rows]


def count_jobs_for_user(self, user_id: str) -> int:
    row = self._connection.execute(
        "SELECT COUNT(*) AS count FROM translation_jobs WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["count"])
```

- [ ] **Step 5: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_persistent_jobs
```

Expected: all persistent job tests pass.

---

### Task 3: Service Book Page and Detail APIs

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Test: `tests/test_bot_translation_service.py`

- [ ] **Step 1: Add failing service tests**

Add tests for title propagation, page metadata, detail lookup, and owner-safe access:

```python
def test_lists_user_books_page_with_display_titles(self):
    page = service.list_user_books_page(user_telegram_id=42, page=0, page_size=5)

    self.assertEqual(page.page, 0)
    self.assertEqual(page.page_size, 5)
    self.assertEqual(page.total_books, 2)
    self.assertEqual(page.total_pages, 1)
    self.assertEqual(page.books[0].display_title, "Ave Maria")


def test_gets_user_book_detail_for_owner_only(self):
    detail = service.get_user_book_detail(user_telegram_id=42, job_id=owned_job.id)

    self.assertEqual(detail.job_id, owned_job.id)
    self.assertEqual(detail.display_title, "Ave Maria")
    self.assertEqual(detail.file_name, "raw-file.epub")
    self.assertEqual(detail.status, "ready")
    self.assertTrue(detail.has_result)
    self.assertIsNone(service.get_user_book_detail(user_telegram_id=42, job_id=other_user_job.id))
```

Use the existing setup patterns from `test_loads_specific_persistent_book_result_for_owner`, but create jobs with `display_title`.

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service
```

Expected: fail because page/detail dataclasses and methods do not expose display titles yet.

- [ ] **Step 3: Add display title to service dataclasses**

Update:

```python
@dataclass(frozen=True)
class UserBookSummary:
    job_id: str
    display_title: str
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    status: str
    has_result: bool


@dataclass(frozen=True)
class UserBooksPage:
    books: list[UserBookSummary]
    page: int
    page_size: int
    total_books: int
    total_pages: int


@dataclass(frozen=True)
class UserBookDetail:
    job_id: str
    display_title: str
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    status: str
    has_result: bool
    has_partial_result: bool
    progress_percent: int | None = None
```

- [ ] **Step 4: Store display title when creating persistent jobs**

Where persistent jobs are created from pending uploads, compute:

```python
from translator_service.document_titles import build_display_title

display_title = build_display_title(
    file_name=pending.file_name,
    content=pending.content,
)
```

Pass `display_title=display_title` into `create_job`.

- [ ] **Step 5: Implement page/detail methods**

Add:

```python
def list_user_books_page(
    self,
    *,
    user_telegram_id: int,
    page: int = 0,
    page_size: int = 5,
) -> UserBooksPage:
    if self._persistent_job_store is None:
        return UserBooksPage([], max(0, page), page_size, 0, 0)

    safe_page = max(0, page)
    safe_page_size = min(max(1, page_size), 10)
    total_books = self._persistent_job_store.count_jobs_for_user(f"telegram:{user_telegram_id}")
    total_pages = (total_books + safe_page_size - 1) // safe_page_size
    jobs = self._persistent_job_store.list_jobs_for_user(
        f"telegram:{user_telegram_id}",
        limit=safe_page_size,
        offset=safe_page * safe_page_size,
    )
    return UserBooksPage(
        books=[_user_book_summary_from_job(job) for job in jobs],
        page=safe_page,
        page_size=safe_page_size,
        total_books=total_books,
        total_pages=total_pages,
    )


def get_user_book_detail(
    self,
    *,
    user_telegram_id: int,
    job_id: str,
) -> UserBookDetail | None:
    if self._persistent_job_store is None:
        return None
    job = self._persistent_job_store.get_job(job_id)
    if job is None or job.user_id != f"telegram:{user_telegram_id}":
        return None
    return UserBookDetail(
        job_id=job.id,
        display_title=job.display_title or job.file_name,
        file_name=job.file_name,
        document_kind=job.document_kind,
        source_language=job.source_language,
        target_language=job.target_language,
        status=job.status.value,
        has_result=bool(job.final_object_key or job.partial_object_key),
        has_partial_result=bool(job.partial_object_key),
        progress_percent=None,
    )
```

Extract helper:

```python
def _user_book_summary_from_job(job) -> UserBookSummary:
    return UserBookSummary(
        job_id=job.id,
        display_title=job.display_title or job.file_name,
        file_name=job.file_name,
        document_kind=job.document_kind,
        source_language=job.source_language,
        target_language=job.target_language,
        status=job.status.value,
        has_result=bool(job.final_object_key or job.partial_object_key),
    )
```

- [ ] **Step 6: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service
```

Expected: service tests pass.

---

### Task 4: Localized List and Detail Messages

**Files:**
- Modify: `src/translator_service/bot/messages.py`
- Test: `tests/test_bot_messages.py`

- [ ] **Step 1: Add failing message tests**

Add:

```python
def test_my_books_page_message_uses_display_titles_and_page_number(self):
    message = build_my_books_page_message(
        {
            "books": [
                {
                    "display_title": "Ave Maria",
                    "file_name": "raw-file-name.epub",
                    "document_kind": "epub",
                    "source_language": "ru",
                    "target_language": "uk",
                    "status": "ready",
                    "has_result": True,
                },
            ],
            "page": 0,
            "page_size": 5,
            "total_books": 9,
            "total_pages": 2,
        },
        "ru",
    )

    self.assertIn("Мои книги", message)
    self.assertIn("1. Ave Maria", message)
    self.assertIn("EPUB", message)
    self.assertIn("Страница 1/2", message)
    self.assertNotIn("raw-file-name.epub", message.splitlines()[2])


def test_user_book_detail_message_is_a_polished_card(self):
    message = build_user_book_detail_message(
        {
            "display_title": "Ave Maria",
            "file_name": "raw-file-name.epub",
            "document_kind": "epub",
            "source_language": "ru",
            "target_language": "uk",
            "status": "ready",
            "has_result": True,
            "has_partial_result": False,
            "progress_percent": 100,
        },
        "ru",
    )

    self.assertIn("📘 Ave Maria", message)
    self.assertIn("EPUB · RU -> UK", message.upper())
    self.assertIn("Файл: raw-file-name.epub", message)
    self.assertIn("100%", message)
    self.assertIn("Результат: доступен", message)
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_messages
```

Expected: fail because new builders and title strings do not exist yet.

- [ ] **Step 3: Add localized copy**

Add message keys for all interface languages:

```python
"page": "Page {current}/{total}",
"previous_page": "← Back",
"next_page": "Next →",
"book_file": "File",
"book_status": "Status",
"book_progress": "Progress",
"book_result_available": "Result: available",
"book_result_missing": "Result: not ready yet",
"download_translation": "Download translation",
"back_to_books": "← My Books",
```

Use equivalent Russian/Ukrainian/French/Spanish/Dutch text.

- [ ] **Step 4: Implement page/detail builders**

Add:

```python
def build_my_books_page_message(page, interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    books = _book_value(page, "books") or []
    if not books:
        return f"{messages['my_books_title']}\n\n{messages['my_books_empty']}"

    lines = [messages["my_books_title"], ""]
    for index, book in enumerate(books, start=1):
        value = _book_value(book)
        title = value.get("display_title") or value.get("file_name", "-")
        availability = messages["download_available"] if value.get("has_result") else messages["download_missing"]
        lines.append(
            f"{index}. {title}\n"
            f"   {str(value.get('document_kind', '-')).upper()}"
            f" · {str(value.get('source_language', '-')).upper()} -> {str(value.get('target_language', '-')).upper()}"
            f" · {value.get('status', '-')}"
            f" · {availability}"
        )

    total_pages = max(1, int(_book_value(page, "total_pages") or 1))
    current_page = int(_book_value(page, "page") or 0) + 1
    lines.extend(["", messages["page"].format(current=current_page, total=total_pages)])
    return "\n".join(lines)


def build_user_book_detail_message(book, interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    value = _book_value(book)
    title = value.get("display_title") or value.get("file_name", "-")
    result_line = messages["book_result_available"] if value.get("has_result") else messages["book_result_missing"]
    progress = value.get("progress_percent")
    lines = [
        f"📘 {title}",
        "",
        f"{str(value.get('document_kind', '-')).upper()} · {str(value.get('source_language', '-')).upper()} -> {str(value.get('target_language', '-')).upper()}",
        "",
        f"{messages['book_status']}: {value.get('status', '-')}",
    ]
    if progress is not None:
        lines.append(f"{messages['book_progress']}: {progress}%")
    lines.append(result_line)
    lines.extend(["", f"{messages['book_file']}: {value.get('file_name', '-')}"])
    return "\n".join(lines)
```

- [ ] **Step 5: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_messages
```

Expected: message tests pass.

---

### Task 5: Runtime Title Buttons and Callback Payloads

**Files:**
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Add failing keyboard tests**

Add:

```python
def test_my_books_page_keyboard_uses_book_title_buttons(self):
    keyboard = _my_books_page_keyboard(
        {
            "books": [
                {"job_id": "job-1", "display_title": "Ave Maria", "document_kind": "epub", "has_result": True},
                {"job_id": "job-2", "display_title": "Stress Test Document", "document_kind": "docx", "has_result": False},
            ],
            "page": 1,
            "total_pages": 3,
        },
        interface_language="en",
    )

    self.assertEqual(
        [[(button.text, button.callback_data) for button in row] for row in keyboard.inline_keyboard],
        [
            [("📘 Ave Maria", "books:detail:job-1:1")],
            [("📄 Stress Test Document", "books:detail:job-2:1")],
            [("← Back", "books:page:0"), ("Next →", "books:page:2")],
        ],
    )


def test_book_detail_keyboard_shows_download_when_result_exists(self):
    keyboard = _book_detail_keyboard(
        {"job_id": "job-1", "has_result": True},
        page=2,
        interface_language="en",
    )

    self.assertEqual(
        [[(button.text, button.callback_data) for button in row] for row in keyboard.inline_keyboard],
        [
            [("Download translation", "book:download:job-1")],
            [("← My Books", "books:page:2")],
        ],
    )
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime
```

Expected: fail because title-button keyboard functions do not exist yet.

- [ ] **Step 3: Implement title-button helpers**

Add:

```python
MY_BOOKS_PAGE_SIZE = 5


def _my_books_page_keyboard(page, interface_language: str = "en"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    current_page = int(_page_value(page, "page") or 0)
    for book in _page_books(page):
        job_id = _book_job_id(book)
        if not job_id:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_book_button_text(book),
                    callback_data=f"books:detail:{job_id}:{current_page}",
                )
            ]
        )

    nav = []
    total_pages = int(_page_value(page, "total_pages") or 0)
    if current_page > 0:
        nav.append(InlineKeyboardButton(text=get_previous_page_text(interface_language), callback_data=f"books:page:{current_page - 1}"))
    if total_pages and current_page < total_pages - 1:
        nav.append(InlineKeyboardButton(text=get_next_page_text(interface_language), callback_data=f"books:page:{current_page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=get_main_menu_button_text(interface_language), callback_data="books:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _book_button_text(book) -> str:
    from translator_service.document_titles import shorten_button_title

    title = _book_value(book, "display_title") or _book_value(book, "file_name") or "-"
    icon = "📘" if str(_book_value(book, "document_kind")).lower() == "epub" else "📄"
    return f"{icon} {shorten_button_title(str(title))}"
```

Add `_book_detail_keyboard` with download and back-to-list buttons:

```python
def _book_detail_keyboard(book, *, page: int, interface_language: str = "en"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    job_id = _book_job_id(book)
    if job_id and _book_has_result(book):
        rows.append([InlineKeyboardButton(text=get_download_translation_text(interface_language), callback_data=f"book:download:{job_id}")])
    rows.append([InlineKeyboardButton(text=get_back_to_books_text(interface_language), callback_data=f"books:page:{max(0, page)}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
```

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime
```

Expected: runtime keyboard tests pass.

---

### Task 6: Wire Telegram List, Page, Detail, and Download Callbacks

**Files:**
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Add callback parser tests**

Add:

```python
def test_extracts_page_number_from_callback_data(self):
    self.assertEqual(_book_page_from_callback_data("books:page:2"), 2)
    self.assertEqual(_book_page_from_callback_data("books:page:-1"), 0)
    self.assertEqual(_book_page_from_callback_data("books:page:oops"), 0)


def test_extracts_book_detail_callback_parts(self):
    self.assertEqual(
        _book_detail_from_callback_data("books:detail:job-42:3"),
        ("job-42", 3),
    )
    self.assertEqual(
        _book_detail_from_callback_data("books:detail:job-42"),
        ("job-42", 0),
    )
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime
```

Expected: fail because callback parsers do not exist.

- [ ] **Step 3: Implement callbacks**

Replace current `my_books` handler with page API:

```python
@router.message(F.text.func(is_my_books_text))
async def my_books(message: Message) -> None:
    interface_language = service.get_interface_language(message.from_user.id)
    page = service.list_user_books_page(
        user_telegram_id=message.from_user.id,
        page=0,
        page_size=MY_BOOKS_PAGE_SIZE,
    )
    await message.answer(
        build_my_books_page_message(page, interface_language=interface_language),
        reply_markup=_my_books_page_keyboard(page, interface_language=interface_language),
    )
```

Add page callback:

```python
@router.callback_query(F.data.startswith("books:page:"))
async def books_page(callback: CallbackQuery) -> None:
    interface_language = service.get_interface_language(callback.from_user.id)
    page_number = _book_page_from_callback_data(callback.data)
    page = service.list_user_books_page(
        user_telegram_id=callback.from_user.id,
        page=page_number,
        page_size=MY_BOOKS_PAGE_SIZE,
    )
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        build_my_books_page_message(page, interface_language=interface_language),
        reply_markup=_my_books_page_keyboard(page, interface_language=interface_language),
    )
    await callback.answer()
```

Add detail callback:

```python
@router.callback_query(F.data.startswith("books:detail:"))
async def book_detail(callback: CallbackQuery) -> None:
    interface_language = service.get_interface_language(callback.from_user.id)
    job_id, page_number = _book_detail_from_callback_data(callback.data)
    detail = service.get_user_book_detail(
        user_telegram_id=callback.from_user.id,
        job_id=job_id,
    )
    if detail is None or callback.message is None:
        await callback.answer(build_download_unavailable_message(interface_language), show_alert=True)
        return
    await callback.message.edit_text(
        build_user_book_detail_message(detail, interface_language=interface_language),
        reply_markup=_book_detail_keyboard(detail, page=page_number, interface_language=interface_language),
    )
    await callback.answer()
```

Update download callback to use `book:download:<job_id>` and keep the old `download_book:<job_id>` prefix for one dev cycle:

```python
@router.callback_query(F.data.startswith("book:download:") | F.data.startswith("download_book:"))
async def download_book(callback: CallbackQuery) -> None:
    data = callback.data or ""
    job_id = data.rsplit(":", 1)[1]
    ...
```

- [ ] **Step 4: Verify runtime tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime
```

Expected: runtime tests pass.

---

### Task 7: Update TЗ and Run Full Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-05-03-deepseek-document-telegram-bot-design.md`

- [ ] **Step 1: Update design spec**

In `My Books and Translation History`, record:

```markdown
Current Telegram dev behavior:

- `My Books` displays recent translations in pages of five.
- List rows use display titles from document metadata when available, falling back to a cleaned file name.
- Inline list buttons use readable book-title labels such as `📘 Ave Maria`, not numeric `Open 1` labels.
- Pressing a title opens the book detail screen.
- The detail screen shows display title, original file name, source and target language, status, progress when known, and result availability.
- The detail screen is formatted as a clean text card: title first, compact format/language line second, status/progress/result block, then original file name.
- Download actions live on the detail screen and validate Telegram user ownership by `job_id`.
```

- [ ] **Step 2: Run full test suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 3: Compile source**

Run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex-pycache PYTHONPATH=src python3 -m compileall src
```

Expected: compile completes without errors.

- [ ] **Step 4: Check whitespace**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 5: Manual Telegram smoke test**

Run dev bot:

```bash
scripts/run_bot_env.sh .env.dev
```

In Telegram:

1. Open `Мои книги`.
2. Confirm first page lists up to five books with readable titles.
3. Confirm inline buttons use book names, not numeric open/download labels.
4. Press next page and previous page.
5. Press a book-title button.
6. Confirm the detail screen reads like a book card, not a technical log.
7. Download an available result from the detail screen.
8. Return to the list.

- [ ] **Step 6: Commit**

Run:

```bash
git add docs/superpowers/specs/2026-05-03-deepseek-document-telegram-bot-design.md docs/superpowers/plans/2026-05-08-my-books-detail-ui.md src/translator_service/document_titles.py src/translator_service/persistent_jobs.py src/translator_service/bot_translation_service.py src/translator_service/bot/messages.py src/translator_service/bot/runtime.py tests/test_document_titles.py tests/test_persistent_jobs.py tests/test_bot_translation_service.py tests/test_bot_messages.py tests/test_bot_runtime.py
git commit -m "feat: add titled my books detail UI"
```

---

## Self-Review

- Spec coverage: covers paginated `My Books`, metadata-based display titles, title buttons, polished book-card detail screen, owner-checked downloads, and future positions for resume/cover actions.
- Placeholder scan: no placeholder markers or unspecified implementation steps.
- Type consistency: title fields are introduced at document-title extraction and persistent-job storage before service, message, and runtime layers consume them.
