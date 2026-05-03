# DeepSeek Document Telegram Bot Implementation Plan


**Goal:** Build an independent Telegram bot for paid EPUB, DOCX, PDF, and TXT translation through DeepSeek API.

**Architecture:** The service uses separate bot, API, worker, queue, database, storage, and DeepSeek integration boundaries. The MVP starts with a thin tested skeleton, then adds document intake, pricing, balance, background translation, and admin operations in vertical slices.

**Tech Stack:** Python, aiogram, FastAPI, PostgreSQL, Redis, Celery or RQ, S3-compatible storage, Docker Compose, pytest.

---

### Task 1: Runnable Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `src/translator_service/config.py`
- Create: `src/translator_service/api.py`
- Create: `src/translator_service/bot/messages.py`
- Create: `tests/test_config.py`
- Create: `tests/test_api.py`
- Create: `tests/test_bot_messages.py`

- [ ] Write failing tests for configuration, API healthcheck, and bot greeting.
- [ ] Run `PYTHONPATH=src python3 -m unittest discover -s tests` and confirm tests fail because modules do not exist.
- [ ] Implement minimal code to satisfy the tests.
- [ ] Run `PYTHONPATH=src python3 -m unittest discover -s tests` and confirm tests pass.
- [ ] Commit the skeleton.

### Task 2: User Registration and Menu

- [ ] Add user model and repository interface.
- [ ] Add `/start` handler that creates or updates user records.
- [ ] Add menu rendering.
- [ ] Test first-time and returning user flows.

### Task 3: Document Upload Draft Order

- [ ] Validate supported extensions and size.
- [ ] Store uploaded files through a storage interface.
- [ ] Create draft order records.
- [ ] Test accepted and rejected file cases.

### Task 4: Text Extraction and Price Estimate

- [ ] Add extractors for TXT, DOCX, EPUB, and basic PDF.
- [ ] Estimate characters, fragments, and token volume.
- [ ] Calculate price from configurable tariffs.
- [ ] Test extraction and pricing behavior.

### Task 5: Balance and Payment Ledger

- [ ] Add balance and payment tables.
- [ ] Add admin balance adjustment.
- [ ] Add order charge and refund flows.
- [ ] Test insufficient balance, charge, and refund.

### Task 6: Queue and Worker

- [ ] Add Redis-backed queue.
- [ ] Add worker entrypoint.
- [ ] Store task status and fragment progress.
- [ ] Test status transitions and retryable failures.

### Task 7: DeepSeek Translation

- [ ] Add DeepSeek client wrapper.
- [ ] Add timeout, retry, and rate-limit handling.
- [ ] Track token usage and cost.
- [ ] Test through mocked API responses.

### Task 8: Result Assembly

- [ ] Assemble translated TXT.
- [ ] Assemble translated DOCX.
- [ ] Assemble translated EPUB.
- [ ] Return PDF translations as TXT or DOCX for MVP.
- [ ] Test fragment ordering and resumed tasks.

### Task 9: History, TTL, and Admin Tools

- [ ] Add translation history.
- [ ] Add file expiration and cleanup job.
- [ ] Add admin commands for errors, retries, refunds, limits, and statistics.
- [ ] Test cleanup and admin authorization.
