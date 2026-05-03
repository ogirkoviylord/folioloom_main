# DeepSeek Document Telegram Bot Design

## Goal

Build an independent Telegram service for paid document translation through DeepSeek API. The service accepts EPUB, DOCX, PDF, and TXT files, estimates price before work starts, runs translation in background workers, and returns a translated file to the user.

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

1. User sends a document to the Telegram bot.
2. The bot validates format and size.
3. The service stores the original file and creates an order.
4. The analyzer extracts text and estimates volume.
5. The bot shows language options, quality mode, price, and expected time.
6. User confirms and pays from balance.
7. The order is queued.
8. Worker splits the document into ordered fragments.
9. Worker translates fragments through DeepSeek API.
10. Worker assembles a translated file.
11. Bot sends the result and stores it in history until file TTL expires.

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
