import hashlib
import json
import unittest
from pathlib import Path

from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_prepared_prep_service import (
    DEFAULT_PREPARED_GLOSSARY_ESTIMATED_EDITOR_TOKENS,
    DEFAULT_PREPARED_GLOSSARY_MAX_CANDIDATES,
    DEFAULT_PREPARED_GLOSSARY_MAX_EXCERPT_CHARS,
    DEFAULT_PREPARED_GLOSSARY_MAX_FRAGMENT_CHARS,
    DEFAULT_PREPARED_GLOSSARY_MIN_DIAGNOSTIC_SCORE,
    DEFAULT_PREPARED_GLOSSARY_MIN_EDITOR_SCORE,
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

    def test_default_cap_keeps_sixteen_bounded_durable_candidates(self):
        content = _many_place_content()
        request = _request(content)
        provider_requests = []

        def provider(provider_request):
            provider_requests.append(provider_request)
            return _package_from_all_candidates(provider_request.packet)

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertTrue(result.enabled)
        self.assertEqual(len(provider_requests), 1)
        packet = provider_requests[0].packet
        self.assertEqual(packet["max_candidates"], 16)
        self.assertEqual(
            packet["max_candidates"],
            DEFAULT_PREPARED_GLOSSARY_MAX_CANDIDATES,
        )
        self.assertEqual(len(packet["candidates"]), 16)
        self.assertEqual(result.metadata["max_candidates"], 16)
        self.assertEqual(
            result.metadata["max_estimated_editor_tokens"],
            DEFAULT_PREPARED_GLOSSARY_ESTIMATED_EDITOR_TOKENS,
        )
        self.assertEqual(
            result.metadata["caps"]["max_candidates"],
            DEFAULT_PREPARED_GLOSSARY_MAX_CANDIDATES,
        )
        self.assertEqual(
            result.metadata["caps"]["max_excerpt_chars"],
            DEFAULT_PREPARED_GLOSSARY_MAX_EXCERPT_CHARS,
        )
        self.assertEqual(
            result.metadata["caps"]["max_fragment_chars"],
            DEFAULT_PREPARED_GLOSSARY_MAX_FRAGMENT_CHARS,
        )
        self.assertEqual(
            result.metadata["caps"]["max_estimated_editor_tokens"],
            DEFAULT_PREPARED_GLOSSARY_ESTIMATED_EDITOR_TOKENS,
        )
        self.assertEqual(
            result.metadata["caps"]["min_editor_score"],
            DEFAULT_PREPARED_GLOSSARY_MIN_EDITOR_SCORE,
        )
        self.assertEqual(
            result.metadata["caps"]["min_diagnostic_score"],
            DEFAULT_PREPARED_GLOSSARY_MIN_DIAGNOSTIC_SCORE,
        )
        self.assertEqual(result.metadata["selected_candidate_count"], 16)
        self.assertEqual(result.metadata["validation"]["ready_entry_count"], 16)
        self.assertEqual(
            result.metadata["candidate_quality"]["selected_candidate_count"],
            16,
        )
        self.assertEqual(
            result.metadata["candidate_quality"]["dropped_candidate_count"],
            0,
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Aldor Keep", metadata_text)
        self.assertNotIn("Rhea Garden", metadata_text)

    def test_candidate_cap_changes_selector_and_package_signatures(self):
        content = _many_place_content()
        request = _request(content)

        def prepare_with_cap(cap):
            provider_requests = []

            def provider(provider_request):
                provider_requests.append(provider_request)
                return _package_from_all_candidates(provider_request.packet)

            result = PreparedGlossaryPrepService(
                provider=provider,
                config=PreparedGlossaryPrepServiceConfig(
                    max_candidates=cap,
                    max_estimated_editor_tokens=max(2_400, cap * 300),
                ),
            ).prepare(request)
            return result, provider_requests[0].packet

        cap_8, packet_8 = prepare_with_cap(8)
        cap_16, packet_16 = prepare_with_cap(16)

        self.assertTrue(cap_8.enabled)
        self.assertTrue(cap_16.enabled)
        self.assertEqual(len(packet_8["candidates"]), 8)
        self.assertEqual(len(packet_16["candidates"]), 16)
        self.assertNotEqual(
            cap_8.metadata["candidate_selector_signature"],
            cap_16.metadata["candidate_selector_signature"],
        )
        self.assertNotEqual(
            cap_8.metadata["validation"]["package_signature"],
            cap_16.metadata["validation"]["package_signature"],
        )
        self.assertEqual(cap_8.metadata["max_candidates"], 8)
        self.assertEqual(cap_16.metadata["max_candidates"], 16)
        self.assertEqual(cap_8.metadata["caps"]["max_candidates"], 8)
        self.assertEqual(cap_16.metadata["caps"]["max_candidates"], 16)

    def test_configured_prep_caps_are_reflected_in_packet_and_metadata(self):
        content = _many_place_content()
        request = _request(content)
        provider_requests = []

        def provider(provider_request):
            provider_requests.append(provider_request)
            return _package_from_all_candidates(provider_request.packet)

        result = PreparedGlossaryPrepService(
            provider=provider,
            config=PreparedGlossaryPrepServiceConfig(
                max_candidates=3,
                max_excerpt_chars=64,
                max_fragment_chars=640,
                max_estimated_editor_tokens=1_800,
                min_editor_score=1,
                min_diagnostic_score=1,
                max_provider_reported_total_tokens=500,
            ),
        ).prepare(request)

        self.assertTrue(result.enabled)
        self.assertEqual(len(provider_requests), 1)
        packet = provider_requests[0].packet
        self.assertEqual(packet["max_candidates"], 3)
        self.assertEqual(packet["max_excerpt_chars"], 64)
        self.assertLessEqual(len(packet["candidates"]), 3)
        self.assertEqual(result.metadata["caps"]["max_candidates"], 3)
        self.assertEqual(result.metadata["caps"]["max_excerpt_chars"], 64)
        self.assertEqual(result.metadata["caps"]["max_fragment_chars"], 640)
        self.assertEqual(
            result.metadata["caps"]["max_estimated_editor_tokens"],
            1_800,
        )
        self.assertEqual(
            result.metadata["caps"]["max_provider_reported_total_tokens"],
            500,
        )

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

    def test_provider_low_value_package_is_not_ready(self):
        request = _request(_source_content(), target_language="ru")

        def provider(provider_request):
            payload = _package_from_packet(provider_request.packet)
            payload["entries"][0]["source_entry_id"] = "entry:then-he"
            payload["entries"][0]["source_canonical"] = "Then He"
            payload["entries"][0]["aliases"] = ["Then", "He"]
            return payload

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.payload)
        self.assertEqual(result.metadata["validation"]["status"], "needs_review")
        self.assertIn(
            "prepared_glossary_package_quality_no_ready_entries",
            result.reason_codes,
        )
        self.assertEqual(
            result.metadata["validation"]["quality"]["dropped_candidate_count"],
            1,
        )
        self.assertNotIn(
            "Then He",
            json.dumps(result.metadata, ensure_ascii=False),
        )

    def test_provider_pg17460_low_value_package_is_not_ready(self):
        request = _request(_source_content(), target_language="ru")

        def provider(provider_request):
            payload = _package_from_packet(provider_request.packet)
            payload["entries"] = [
                _prepared_package_entry(
                    source_entry_id="entry:boy-and",
                    source_canonical="BOY AND",
                    aliases=["BOY AND"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:of-any-kind",
                    source_canonical="OF ANY KIND",
                    aliases=["OF ANY KIND"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:labour-was",
                    source_canonical="Labour Was",
                    aliases=["Labour Was"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:good-god",
                    source_canonical="Good God",
                    aliases=["Good God"],
                ),
            ]
            return payload

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertFalse(result.enabled)
        self.assertIsNone(result.payload)
        self.assertEqual(result.metadata["validation"]["status"], "needs_review")
        self.assertIn(
            "prepared_glossary_package_quality_no_ready_entries",
            result.reason_codes,
        )
        self.assertEqual(
            result.metadata["validation"]["quality"]["dropped_candidate_count"],
            4,
        )
        self.assertIn(
            "candidate_quality_function_word_phrase",
            result.metadata["validation"]["quality"]["reason_codes"],
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        for raw_source in ("BOY AND", "OF ANY KIND", "Labour Was", "Good God"):
            self.assertNotIn(raw_source, metadata_text)

    def test_mixed_ready_provider_package_returns_sanitized_payload(self):
        request = _request(_source_content(), target_language="ru")

        def provider(provider_request):
            payload = _package_from_packet(provider_request.packet)
            payload["entries"] = [
                _prepared_package_entry(
                    source_entry_id="entry:labour-exchange",
                    source_canonical="Labour Exchange",
                    aliases=[
                        "Labour Exchange",
                        "Labour Was",
                        "OF ANY KIND",
                        "Good God",
                    ],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:boy-and",
                    source_canonical="BOY AND",
                    aliases=["BOY AND"],
                ),
            ]
            return payload

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertTrue(result.enabled)
        self.assertIsInstance(result.payload, dict)
        payload = result.payload
        assert isinstance(payload, dict)
        entries = payload["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source_entry_id"], "entry:labour-exchange")
        self.assertEqual(entries[0]["source_canonical"], "Labour Exchange")
        self.assertEqual(entries[0]["aliases"], ["Labour Exchange"])
        payload_text = json.dumps(result.payload, ensure_ascii=False)
        for unsafe in ("BOY AND", "Labour Was", "OF ANY KIND", "Good God"):
            self.assertNotIn(unsafe, payload_text)
        quality = result.metadata["validation"]["quality"]
        self.assertEqual(quality["dropped_candidate_count"], 1)
        self.assertEqual(quality["alias_omitted_count"], 4)
        self.assertEqual(quality["selected_candidate_count"], 1)
        self.assertTrue(result.metadata["metadata_only"])
        self.assertFalse(result.metadata["raw_payload_included"])
        self.assertTrue(result.metadata["validation"]["metadata_only"])
        self.assertFalse(result.metadata["validation"]["raw_payload_included"])
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        for raw_source in (
            "Labour Exchange",
            "BOY AND",
            "Labour Was",
            "OF ANY KIND",
            "Good God",
        ):
            self.assertNotIn(raw_source, metadata_text)

    def test_provider_mixed_artifact_package_prunes_broad_aliases(self):
        request = _request(_source_content(), target_language="ru")

        def provider(provider_request):
            payload = _package_from_packet(provider_request.packet)
            payload["entries"] = [
                _prepared_package_entry(
                    source_entry_id="entry:alice-winterbourne",
                    source_canonical="Alice Winterbourne",
                    aliases=["Alice", "Winterbourne", "Lizzy"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:darcy-possessive",
                    source_canonical="Mr Darcy's",
                    aliases=["Mr Darcy's"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:darcy-curly-possessive",
                    source_canonical="Mr Darcy’s",
                    aliases=["Mr Darcy’s"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:oh-john",
                    source_canonical="Oh John",
                    aliases=["Oh John"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:macy-department-store-curly",
                    source_canonical="Macy’s Department Store",
                    aliases=["Macy’s Department Store"],
                ),
                _prepared_package_entry(
                    source_entry_id="entry:oh-canada",
                    source_canonical="Oh Canada",
                    aliases=["Oh Canada"],
                ),
            ]
            return payload

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertTrue(result.enabled)
        self.assertIsInstance(result.payload, dict)
        payload = result.payload
        assert isinstance(payload, dict)
        entries = payload["entries"]
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["source_canonical"], "Alice Winterbourne")
        self.assertEqual(entries[0]["aliases"], ["Winterbourne", "Lizzy"])
        self.assertEqual(entries[1]["source_canonical"], "Macy’s Department Store")
        self.assertEqual(entries[1]["aliases"], ["Macy’s Department Store"])
        self.assertEqual(entries[2]["source_canonical"], "Oh Canada")
        self.assertEqual(entries[2]["aliases"], ["Oh Canada"])
        quality = result.metadata["validation"]["quality"]
        self.assertEqual(quality["dropped_candidate_count"], 3)
        self.assertEqual(quality["alias_omitted_count"], 4)
        self.assertIn("candidate_quality_possessive_source", quality["reason_codes"])
        self.assertIn("candidate_quality_vocative_phrase", quality["reason_codes"])
        self.assertIn("candidate_quality_broad_alias_pruned", quality["reason_codes"])
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Mr Darcy's", metadata_text)
        self.assertNotIn("Mr Darcy’s", metadata_text)
        self.assertNotIn("Oh John", metadata_text)
        self.assertNotIn("Alice Winterbourne", metadata_text)
        self.assertNotIn("Macy’s Department Store", metadata_text)
        self.assertNotIn("Oh Canada", metadata_text)

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

    def test_low_value_candidates_fall_back_before_provider(self):
        provider_calls = []
        content = (
            b"Then He walked away. Then He returned. "
            b"Now He waited. Now He spoke. "
            b"But He listened. But He answered. "
            b"In God we trust. In God we wait."
        )
        request = _request(content)

        result = PreparedGlossaryPrepService(
            provider=lambda provider_request: provider_calls.append(provider_request),
        ).prepare(request)

        self.assertFalse(result.enabled)
        self.assertEqual(provider_calls, [])
        self.assertIn(
            "prepared_glossary_prep_candidate_quality_no_candidates",
            result.reason_codes,
        )
        self.assertEqual(result.metadata["selected_candidate_count"], 0)
        self.assertEqual(
            result.metadata["candidate_quality"]["selected_candidate_count"],
            0,
        )
        self.assertGreater(
            result.metadata["candidate_quality"]["dropped_candidate_count"],
            0,
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Then He", metadata_text)
        self.assertNotIn("In God", metadata_text)

    def test_candidate_quality_prunes_packet_aliases_and_keeps_valid_candidates(self):
        content = (
            b"Then He walked away. Then He returned. "
            b"Mr. Darcy met Alice at Pemberley. "
            b"Darcy returned to Pemberley with Alice. "
            b"Mr. Darcy wrote to Alice again."
        )
        request = _request(content)
        provider_requests = []

        def provider(provider_request):
            provider_requests.append(provider_request)
            return _package_from_packet(provider_request.packet)

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertTrue(result.enabled)
        self.assertEqual(len(provider_requests), 1)
        packet_candidates = provider_requests[0].packet["candidates"]
        sources = [candidate["source_canonical"] for candidate in packet_candidates]
        aliases = {
            alias
            for candidate in packet_candidates
            for alias in candidate["aliases"]
        }
        self.assertNotIn("Then He", sources)
        self.assertNotIn("Then", aliases)
        self.assertNotIn("He", aliases)
        self.assertTrue({"Mr Darcy", "Alice", "Pemberley"} & set(sources))
        self.assertGreater(
            result.metadata["candidate_quality"]["dropped_candidate_count"],
            0,
        )
        self.assertGreater(
            result.metadata["candidate_quality"]["alias_omitted_count"],
            0,
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Then He", metadata_text)

    def test_candidate_quality_backfills_from_reducer_diagnostics_after_drops(self):
        content = Path(
            "test_samples/gutenberg_time_machine_noimages.en.epub"
        ).read_bytes()
        target_payload = json.loads(
            Path(
                "test_samples/glossary_targets/"
                "gutenberg_time_machine_noimages.runtime-glossary-targets.json"
            ).read_text(encoding="utf-8")
        )
        expected_terms = {
            _term_digest(entry["source_canonical"])
            for entry in target_payload["targets"]["ru"]["entries"]
        }
        request = PreparedGlossaryPackagePrepRequest(
            user_telegram_id=42,
            file_name="gutenberg_time_machine_noimages.en.epub",
            document_kind="epub",
            source_language="en",
            target_language="ru",
            translation_mode="book_manuscript",
            glossary_mode="with_glossary",
            source_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        )
        provider_requests = []

        def provider(provider_request):
            provider_requests.append(provider_request)
            return _package_from_all_candidates(provider_request.packet)

        result = PreparedGlossaryPrepService(provider=provider).prepare(request)

        self.assertTrue(result.enabled)
        self.assertEqual(len(provider_requests), 1)
        packet_candidates = provider_requests[0].packet["candidates"]
        packet_terms = {
            _term_digest(candidate["source_canonical"])
            for candidate in packet_candidates
        }
        self.assertTrue(
            all(candidate["evidence"] for candidate in packet_candidates),
        )
        self.assertTrue(expected_terms & packet_terms)
        self.assertLessEqual(
            len(packet_candidates),
            DEFAULT_PREPARED_GLOSSARY_MAX_CANDIDATES,
        )
        self.assertEqual(
            len(packet_candidates),
            result.metadata["candidate_quality"]["selected_candidate_count"],
        )
        self.assertEqual(
            result.metadata["selected_candidate_count"],
            result.metadata["candidate_quality"]["selected_candidate_count"],
        )
        self.assertGreater(
            result.metadata["candidate_quality"]["dropped_candidate_count"],
            0,
        )
        self.assertGreater(
            result.metadata["candidate_quality"]["input_candidate_count"],
            result.metadata["candidate_quality"]["selected_candidate_count"],
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        for entry in target_payload["targets"]["ru"]["entries"]:
            self.assertNotIn(entry["source_canonical"], metadata_text)

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


def _many_place_content() -> bytes:
    names = (
        "Aldor Keep",
        "Beren Gate",
        "Calion Tower",
        "Daria Harbor",
        "Eldrin Road",
        "Fara Bridge",
        "Galen Forge",
        "Helia Shrine",
        "Ivor Hall",
        "Jorin Market",
        "Kara Wood",
        "Lorin River",
        "Mira Field",
        "Nolan Abbey",
        "Orin Square",
        "Pavel Mill",
        "Quinn House",
        "Rhea Garden",
    )
    text = " ".join(
        (
            f'Archivists named "{name}" in the old map. '
            f'The route to "{name}" appears again in the ledger. '
            f'Travelers remembered "{name}" clearly.'
        )
        for name in names
    )
    return text.encode()


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


def _term_digest(term: str) -> str:
    return hashlib.sha256(term.casefold().encode("utf-8")).hexdigest()[:16]


def _prepared_package_entry(
    *,
    source_entry_id: str,
    source_canonical: str,
    aliases: list[str],
) -> dict:
    return {
        "source_entry_id": source_entry_id,
        "source_canonical": source_canonical,
        "aliases": aliases,
        "evidence_refs": ["ev:1"],
        "target_canonical": "Target",
        "target_variants": ["Target Variant"],
        "forbidden_variants": [],
        "strategy": "fake_provider_only",
        "confidence": 0.91,
        "needs_review": False,
        "reason_codes": [],
    }


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


def _package_from_all_candidates(
    packet,
    *,
    target_language: str | None = None,
) -> dict:
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
                "target_canonical": f"Target {index}",
                "target_variants": [f"Target Variant {index}"],
                "forbidden_variants": [],
                "strategy": "fake_provider_only",
                "confidence": 0.91,
                "needs_review": False,
                "reason_codes": [],
            }
            for index, candidate in enumerate(packet["candidates"], start=1)
        ],
    }


if __name__ == "__main__":
    unittest.main()
