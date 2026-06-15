import hashlib
import json
import unittest

from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_prepared_prep_service import (
    PreparedGlossaryPackagePrepRequest,
    PreparedGlossaryPrepService,
    PreparedGlossaryPrepServiceConfig,
    PreparedGlossaryProviderResponse,
)


class PreparedGlossaryPrepServiceTests(unittest.TestCase):
    def test_fake_provider_ready_package_returns_attachment(self):
        content = _source_content()
        request = _request(content)
        provider_requests = []

        def provider(provider_request):
            provider_requests.append(provider_request)
            return _package_from_packet(provider_request.packet)

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertTrue(result.enabled)
        self.assertIsInstance(result.payload, dict)
        self.assertEqual(result.source_sha256, request.source_sha256)
        self.assertEqual(result.document_kind, "txt")
        self.assertEqual(result.target_language, "ru")
        self.assertEqual(result.reason_codes, ())
        self.assertEqual(result.metadata["status"], "ready")
        self.assertTrue(result.metadata["metadata_only"])
        self.assertFalse(result.metadata["raw_payload_included"])
        self.assertGreater(result.metadata["selected_candidate_count"], 0)
        self.assertEqual(len(provider_requests), 1)
        self.assertIn("candidates", provider_requests[0].packet)
        self.assertNotIn("Darcy", json.dumps(result.metadata, ensure_ascii=False))

    def test_missing_provider_returns_metadata_only_fallback(self):
        request = _request(_source_content())

        result = PreparedGlossaryPrepService(provider=None).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.payload)
        self.assertIn("prepared_glossary_prep_provider_missing", result.reason_codes)
        self.assertEqual(result.metadata["status"], "skipped")
        self.assertTrue(result.metadata["metadata_only"])
        self.assertFalse(result.metadata["raw_payload_included"])

    def test_without_glossary_is_disabled_without_calling_provider(self):
        provider_calls = []
        content = _source_content()
        request = PreparedGlossaryPackagePrepRequest(
            user_telegram_id=42,
            file_name="sample.txt",
            document_kind="txt",
            source_language="en",
            target_language="ru",
            translation_mode="book_manuscript",
            glossary_mode="without_glossary",
            source_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )

        result = PreparedGlossaryPrepService(
            provider=lambda provider_request: provider_calls.append(provider_request)
        ).prepare(request)

        self.assertFalse(result.enabled)
        self.assertEqual(provider_calls, [])
        self.assertIn("prepared_glossary_prep_not_requested", result.reason_codes)
        self.assertEqual(result.metadata["status"], "disabled")
        self.assertTrue(result.metadata["metadata_only"])
        self.assertNotIn("Darcy", json.dumps(result.metadata, ensure_ascii=False))

    def test_source_mismatch_falls_back_without_calling_provider(self):
        provider_calls = []
        request = _request(_source_content(), source_sha256="0" * 64)

        result = PreparedGlossaryPrepService(
            provider=lambda provider_request: provider_calls.append(provider_request)
        ).prepare(request)

        self.assertFalse(result.enabled)
        self.assertEqual(provider_calls, [])
        self.assertIn("prepared_glossary_prep_source_mismatch", result.reason_codes)
        self.assertNotIn("Darcy", json.dumps(result.metadata, ensure_ascii=False))

    def test_target_mismatch_package_is_rejected(self):
        request = _request(_source_content(), target_language="ru")

        def provider(provider_request):
            return _package_from_packet(provider_request.packet, target_language="uk")

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.payload)
        self.assertIn("prepared_glossary_package_target_mismatch", result.reason_codes)
        self.assertEqual(result.metadata["status"], "skipped")
        self.assertEqual(
            result.metadata["validation"]["target_language"],
            "uk",
        )

    def test_invalid_package_schema_is_rejected(self):
        request = _request(_source_content())

        result = PreparedGlossaryPrepService(
            provider=lambda _provider_request: {"schema_version": "bad"}
        ).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.payload)
        self.assertIn(
            "prepared_glossary_package_schema_invalid",
            result.reason_codes,
        )
        self.assertIn(
            "prepared_glossary_package_entries_invalid",
            result.reason_codes,
        )

    def test_raw_and_secret_bearing_package_is_rejected(self):
        request = _request(_source_content())

        def provider(provider_request):
            payload = _package_from_packet(provider_request.packet)
            payload["raw_source_text"] = "Darcy returns."
            payload["api_key"] = "sk-aaaaaaaaaaaaaaaa"
            return payload

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.payload)
        self.assertIn(
            "prepared_glossary_package_raw_field_present",
            result.reason_codes,
        )
        self.assertIn(
            "prepared_glossary_package_secret_field_present",
            result.reason_codes,
        )
        self.assertNotIn("sk-aaaaaaaaaaaaaaaa", json.dumps(result.metadata))
        self.assertNotIn("Darcy returns.", json.dumps(result.metadata))

    def test_no_candidates_falls_back_before_provider(self):
        provider_calls = []
        request = _request(b"and the or but if then with only same")

        result = PreparedGlossaryPrepService(
            provider=lambda provider_request: provider_calls.append(provider_request),
            config=PreparedGlossaryPrepServiceConfig(min_editor_score=9999),
        ).prepare(request)

        self.assertFalse(result.enabled)
        self.assertEqual(provider_calls, [])
        self.assertIn("prepared_glossary_prep_no_candidates", result.reason_codes)
        self.assertEqual(result.metadata["selected_candidate_count"], 0)

    def test_provider_usage_required_falls_back_metadata_only_when_missing(self):
        request = _request(_source_content())

        def provider(provider_request):
            return PreparedGlossaryProviderResponse(
                payload=_package_from_packet(provider_request.packet),
                metadata={"provider_status": "ready"},
            )

        result = PreparedGlossaryPrepService(
            provider=provider,
            config=PreparedGlossaryPrepServiceConfig(require_provider_usage=True),
        ).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.payload)
        self.assertIn(
            "prepared_glossary_prep_provider_usage_missing",
            result.reason_codes,
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertIn("provider_response", result.metadata)
        self.assertNotIn("Darcy returned", metadata_text)

    def test_provider_reported_token_cap_falls_back_metadata_only(self):
        request = _request(_source_content())

        def provider(provider_request):
            return PreparedGlossaryProviderResponse(
                payload=_package_from_packet(provider_request.packet),
                metadata={
                    "provider_status": "ready",
                    "provider_usage": {
                        "prompt_tokens": 50,
                        "completion_tokens": 75,
                        "total_tokens": 125,
                    },
                },
            )

        result = PreparedGlossaryPrepService(
            provider=provider,
            config=PreparedGlossaryPrepServiceConfig(
                max_provider_reported_total_tokens=100,
            ),
        ).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIn(
            "prepared_glossary_prep_provider_token_cap_exceeded",
            result.reason_codes,
        )
        self.assertEqual(
            result.metadata["provider_response"]["provider_usage"]["total_tokens"],
            125,
        )

    def test_provider_metadata_with_raw_or_secret_fields_falls_back(self):
        request = _request(_source_content())

        def provider(provider_request):
            return PreparedGlossaryProviderResponse(
                payload=_package_from_packet(provider_request.packet),
                metadata={
                    "raw_prompt": "Darcy returned to Pemberley.",
                    "api_key": "sk-aaaaaaaaaaaaaaaa",
                },
            )

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIn(
            "prepared_glossary_prep_provider_metadata_raw_field",
            result.reason_codes,
        )
        self.assertIn(
            "prepared_glossary_prep_provider_metadata_secret_field",
            result.reason_codes,
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Darcy returned", metadata_text)
        self.assertNotIn("sk-aaaaaaaaaaaaaaaa", metadata_text)


def _source_content() -> bytes:
    return (
        b"Mr. Darcy met Alice at Pemberley. "
        b"Darcy returned to Pemberley with Alice. "
        b"Mr. Darcy wrote to Alice again."
    )


def _request(
    content: bytes,
    *,
    target_language: str = "ru",
    source_sha256: str | None = None,
) -> PreparedGlossaryPackagePrepRequest:
    return PreparedGlossaryPackagePrepRequest(
        user_telegram_id=42,
        file_name="sample.txt",
        document_kind="txt",
        source_language="en",
        target_language=target_language,
        translation_mode="book_manuscript",
        glossary_mode="with_glossary",
        source_sha256=source_sha256 or hashlib.sha256(content).hexdigest(),
        content=content,
    )


def _package_from_packet(
    packet,
    *,
    target_language: str | None = None,
) -> dict:
    candidate = packet["candidates"][0]
    target = target_language or packet["target_language"]
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": f"prepared:test:{target}",
        "source_language": packet["source_language"],
        "target_language": target,
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": packet["provider_model"],
        "provider_run_id": "provider-run:fake",
        "source_document_fingerprint": packet["source_document_fingerprint"],
        "candidate_selector_signature": packet["candidate_selector_signature"],
        "owner_approved": True,
        "entries": [
            {
                "source_entry_id": candidate["source_entry_id"],
                "source_canonical": candidate["source_canonical"],
                "aliases": candidate["aliases"][:2],
                "evidence_refs": candidate["evidence_refs"][:2],
                "target_canonical": "Дарси",
                "target_variants": ["мистер Дарси"],
                "forbidden_variants": ["Дэрси"],
                "strategy": "fake_provider_only",
                "confidence": 0.91,
                "needs_review": False,
                "reason_codes": [],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
