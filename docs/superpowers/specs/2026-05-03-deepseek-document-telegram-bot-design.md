# DeepSeek Document Telegram Bot Design

## Goal

Build an independent Telegram service for paid document translation through DeepSeek API. The service accepts common text documents first, then expands into ebook, subtitle, office, scanned, and legacy formats. It estimates price before work starts, runs translation in background workers, and returns a translated file to the user.

## Clean-Room Boundary

This project is written from scratch. The implementation must not copy AGPL code, file layout, function or class names, prompts, tests, configuration, or internal architecture from AGPL projects. The project may use general product ideas, public API documentation, open file format documentation, and independently selected permissive libraries.

## MVP Architecture

The MVP is split into small services that can run locally with Docker Compose:

- Telegram bot process for user interaction.
- FastAPI application for healthchecks and internal service endpoints.
- PostgreSQL database for users, orders, payments, settings, and task state.
- Redis-backed queue for background work.
- Worker process for document analysis, translation, and result assembly.
- File storage abstraction with local storage in development and S3-compatible storage later.
- DeepSeek client as the only LLM integration.

The user never chooses an LLM provider. DeepSeek model and pricing settings are controlled by service configuration and admin tools.

## MVP Data Flow

1. User selects the bot interface language.
2. User sends a document to the Telegram bot.
3. The bot validates format and size.
4. The service stores the original file and creates an order.
5. The analyzer extracts text and estimates volume.
6. The bot asks for the target translation language.
7. The bot shows quality mode, price, and expected time.
8. User confirms and pays from balance.
9. The order is queued.
10. Worker splits the document into ordered fragments.
11. Worker translates fragments through DeepSeek API.
12. Worker assembles a translated file.
13. Bot sends the result and stores it in history until file TTL expires.

## Supported Formats

The service must treat file formats as separate adapters. Every adapter has its own extractor, estimator, assembler, and risk label for the user. Unsupported or low-confidence documents must fail before payment.

### MVP Formats

- TXT: plain text input and plain text output.
- DOCX: extract and replace paragraph text while preserving the original DOCX package as much as possible.
- EPUB: translate XHTML content files and preserve ebook metadata, manifest, spine, images, styles, and navigation.
- PDF: support text-layer PDFs first; scanned PDFs require OCR and must be clearly marked as a slower, higher-risk mode.
- RTF: convert rich text to an intermediate representation, translate text runs, and return RTF or DOCX depending on conversion quality.
- FB2: translate XML text nodes while preserving book metadata and structure.
- SRT and VTT: translate subtitle cues while preserving timing, cue numbering, and WebVTT metadata.

### Extended Formats

- ODT: translate OpenDocument text content while preserving package structure and styles where possible.
- HTML and HTM: translate visible text nodes while preserving markup, links, attributes, scripts, and styles.
- MD: translate Markdown prose while preserving headings, lists, links, code blocks, tables, and front matter.
- CSV and TSV: translate selected text columns only; preserve delimiter, quoting, encoding, and row count.
- DjVu: OCR-first format; use only when the document has no reliable embedded text.
- MOBI and AZW3: convert through ebook tooling into EPUB-like content, translate, and return EPUB or converted output when quality allows.

## Third-Party Components for Format Support

The project is written from scratch, but may depend on independent third-party tools and libraries with compatible licenses. Each dependency must be pinned, documented, and isolated behind an adapter so it can be replaced later.

### Text and Encoding

- `charset-normalizer` or equivalent: detect input encoding for TXT, CSV, TSV, SRT, VTT, RTF, and legacy text files.
- Unicode normalization utilities from Python standard library: normalize extracted text before chunking and translation.
- Optional language detection library: detect source language for warnings and analytics, but user-facing translation must not depend on provider selection.

### DOCX

- Python ZIP and XML tooling, or a permissive DOCX library such as `python-docx`: read and write OOXML packages.
- `lxml` or Python XML libraries: preserve XML namespaces and modify text nodes safely.
- No Microsoft Office dependency is required for MVP DOCX support.

### EPUB, HTML, and FB2

- `ebooklib` or equivalent: read EPUB container, manifest, spine, and metadata.
- `beautifulsoup4` plus `lxml` or an equivalent HTML/XML parser: identify visible text nodes and avoid translating scripts/styles.
- XML parser with namespace support for FB2.
- Optional EPUB validation tooling (`epubcheck`) for QA in development or background validation.

### PDF

- `PyMuPDF` (`fitz`) or `pypdf`: extract text-layer PDF content and page structure.
- `poppler` tools or MuPDF command line utilities: render pages to images for OCR fallback and diagnostics.
- For MVP, translated PDF input may produce DOCX or TXT output if faithful PDF reconstruction is not reliable.
- Full PDF reconstruction is an extended feature because layout preservation is expensive and error-prone.

### OCR for Scans, PDF Images, and DjVu

- OCR engine: Tesseract OCR as the default open-source baseline, or PaddleOCR/EasyOCR as optional higher-quality alternatives.
- Language packs: Russian, Ukrainian, English, French, and Spanish OCR data must be installed for the interface and target markets.
- Image preprocessing: OpenCV or Pillow for deskewing, binarization, contrast adjustment, rotation detection, cropping, and page splitting.
- PDF page rendering: Poppler or MuPDF for producing high-resolution page images before OCR.
- DjVu support: DjVuLibre tools (`ddjvu`, `djvutxt`) to extract embedded text or render pages for OCR.
- OCR confidence tracking: low-confidence pages must be flagged before payment or routed to a safer output mode.
- OCR output format: scanned documents should return DOCX or TXT in MVP; preserving the exact original scan layout is an extended feature.

### RTF, ODT, and Office Conversions

- LibreOffice headless mode: convert RTF, ODT, and some legacy office files into DOCX or HTML for extraction and output assembly.
- Pandoc: optional conversion path for RTF, Markdown, HTML, and some ebook/text formats.
- `striprtf` or `unrtf`: lightweight RTF text extraction fallback when full layout preservation is not needed.
- Conversion workers must run in a sandboxed environment with timeouts and file size limits.

### MOBI and AZW3

- Calibre command line tools (`ebook-convert`, `ebook-meta`): convert MOBI/AZW3 to EPUB or HTML-like intermediate content.
- DRM-protected ebooks are not supported; the bot must reject them with a clear user-facing message.
- Output should default to EPUB unless reliable round-trip conversion to the original format is validated.

### Subtitles

- Subtitle parser library or a small independent parser for SRT/VTT timing blocks.
- Timing lines, cue identifiers, styling tags, and speaker markers must be preserved.
- The translator must receive only cue text, not raw timestamp blocks.

### CSV and TSV

- Python `csv` module or equivalent structured parser.
- User must be able to choose which columns to translate in an extended UI; MVP may translate all non-empty text cells with strict row/column preservation.
- Encoding and delimiter detection are required before price estimation.

### Safety, Security, and Operations

- Antivirus scanning such as ClamAV is recommended before processing user-uploaded files.
- Archive and document parsers must run with strict size, page count, timeout, and memory limits.
- External converters must run without network access and with isolated temporary directories.
- Every conversion step must produce structured logs with input format, output format, duration, warnings, and failure reason.
- The system must store original files, intermediate files, and translated results with separate TTL policies.

## User-Facing Format Policy

- The bot must not mention the internal LLM provider.
- The bot may show format-specific warnings, for example: scanned PDF/DjVu translation takes longer; OCR can make recognition mistakes; exact original layout is not guaranteed.
- The bot must ask for confirmation after showing the target language, estimated price, expected time, and output format.
- If a document requires OCR or conversion, that must be included in the estimate before payment.
- If the service cannot preserve the original format reliably, it must offer a safe output format such as DOCX or TXT before charging.

## Translation Modes

The MVP supports user-facing modes, not provider selection:

- Fast: lower-cost default instructions.
- Quality: stricter translation instructions and additional validation where useful.
- Terms: uses user-provided terminology instructions.

All prompts must be written specifically for this project.

## First Development Slice

The first implementation slice creates a runnable backend skeleton with:

- project packaging and test runner;
- typed application settings loaded from environment;
- FastAPI healthcheck endpoint;
- Telegram greeting text builder;
- Docker Compose placeholders for app, bot, worker, PostgreSQL, and Redis.

This slice does not call Telegram, DeepSeek, PostgreSQL, or Redis yet. It establishes the project shape and test discipline before adding external integrations.

## Acceptance Criteria

- `PYTHONPATH=src python3 -m unittest discover -s tests` runs the starter test suite without external dependencies.
- Application settings can be created from environment defaults.
- FastAPI healthcheck returns service name and status.
- Telegram greeting text includes the service purpose and main menu items.
- The repository contains no copied AGPL implementation artifacts.
