import json
import unittest
from types import SimpleNamespace

from translator_service.deepseek_client import DeepSeekUsage
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    validate_prepared_glossary_package,
)
from translator_service.glossary_prepared_prep_service import (
    DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
    PreparedGlossaryProviderRequest,
)
from translator_service.glossary_prepared_provider import (
    DeepSeekPreparedGlossaryProvider,
    build_deepseek_prepared_glossary_provider,
)


class DeepSeekPreparedGlossaryProviderTests(unittest.TestCase):
    def test_entries_only_provider_output_gets_local_envelope(self):
        client = _FakeChatClient(
            {
                "entries": [
                    {
                        "source_entry_id": "entry:darcy",
                        "evidence_refs": ["evidence:darcy"],
                        "target_canonical": "Дарси",
                        "target_variants": ["мистер Дарси"],
                        "forbidden_variants": ["Дэрси"],
                        "strategy": "transcribe",
                        "confidence": 0.91,
                        "needs_review": False,
                        "reason_codes": [],
                    }
                ]
            },
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )
        provider = DeepSeekPreparedGlossaryProvider(client=client)

        response = provider(_provider_request())
        validation = validate_prepared_glossary_package(
            response.payload,
            target_language="ru",
        )

        self.assertTrue(validation.ready)
        self.assertEqual(
            response.payload["provider_model"],
            DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
        )
        self.assertEqual(
            response.payload["provider_role_id"],
            GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        )
        self.assertEqual(response.payload["entries"][0]["source_canonical"], "Darcy")
        self.assertEqual(response.metadata["provider_usage"]["total_tokens"], 120)
        self.assertEqual(
            response.metadata["adjudication"]["mode"],
            "local_envelope_applied",
        )
        metadata_text = json.dumps(response.metadata).lower()
        self.assertNotIn("system_prompt", metadata_text)
        self.assertNotIn("user_text", metadata_text)
        self.assertNotIn("prompt_body", metadata_text)
        self.assertNotIn("Дарси", json.dumps(response.metadata, ensure_ascii=False))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["response_format"], {"type": "json_object"})

    def test_raw_or_secret_bearing_output_is_rejected_before_validation(self):
        client = _FakeChatClient(
            {
                "raw_source_text": "Darcy returns.",
                "entries": [
                    {
                        "source_entry_id": "entry:darcy",
                        "evidence_refs": ["evidence:darcy"],
                        "target_canonical": "Дарси",
                        "confidence": 0.91,
                    }
                ],
            }
        )
        provider = DeepSeekPreparedGlossaryProvider(client=client)

        response = provider(_provider_request())

        self.assertIsNone(response.payload)
        self.assertEqual(response.metadata["provider_status"], "failed")
        self.assertIn(
            "provider_package_raw_field_rejected",
            response.metadata["reason_codes"],
        )
        self.assertNotIn("Darcy returns.", json.dumps(response.metadata))

    def test_invalid_json_returns_metadata_only_failure(self):
        client = _FakeChatClient("not json")
        provider = DeepSeekPreparedGlossaryProvider(client=client)

        response = provider(_provider_request())

        self.assertIsNone(response.payload)
        self.assertIn(
            "prepared_glossary_provider_response_invalid_json",
            response.metadata["reason_codes"],
        )
        self.assertNotIn("not json", json.dumps(response.metadata))

    def test_builder_uses_deepseek_pro_model_for_prep_only(self):
        captured = {}

        def transport(*, url, headers, body, timeout_seconds):
            captured["url"] = url
            captured["headers"] = dict(headers)
            captured["body"] = json.loads(body.decode("utf-8"))
            return 200, json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "entries": [
                                            {
                                                "source_entry_id": "entry:darcy",
                                                "evidence_refs": ["evidence:darcy"],
                                                "target_canonical": "Дарси",
                                                "confidence": 0.91,
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

        provider = build_deepseek_prepared_glossary_provider(
            api_key="unit-test-key",
            base_url="https://deepseek.test",
            transport=transport,
        )

        response = provider(_provider_request())

        self.assertIsNotNone(response.payload)
        self.assertEqual(captured["body"]["model"], "deepseek-v4-pro")
        self.assertEqual(response.metadata["provider_usage"]["total_tokens"], 18)
        self.assertNotIn("Authorization", json.dumps(response.metadata))
        self.assertNotIn("unit-test-key", json.dumps(response.metadata))


class _FakeChatClient:
    def __init__(self, payload, *, usage=None) -> None:
        self.payload = payload
        self.usage = usage or {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
        }
        self.calls = []

    def create_chat_completion(
        self,
        *,
        system_prompt,
        user_text,
        response_format=None,
        allow_empty_content=False,
    ):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_text": user_text,
                "response_format": response_format,
                "allow_empty_content": allow_empty_content,
            }
        )
        content = (
            self.payload
            if isinstance(self.payload, str)
            else json.dumps(self.payload, ensure_ascii=False)
        )
        return SimpleNamespace(
            content=content,
            usage=DeepSeekUsage(
                prompt_tokens=self.usage["prompt_tokens"],
                completion_tokens=self.usage["completion_tokens"],
                total_tokens=self.usage["total_tokens"],
            ),
            finish_reason="stop",
        )


def _provider_request() -> PreparedGlossaryProviderRequest:
    packet = {
        "schema_version": "prepared-glossary-prep-packet-v1",
        "source_language": "en",
        "target_language": "ru",
        "document_kind": "txt",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
        "source_document_fingerprint": "sha256:" + "a" * 64,
        "candidate_selector_signature": "selector:fake",
        "max_candidates": 8,
        "max_excerpt_chars": 1200,
        "candidates": [
            {
                "source_entry_id": "entry:darcy",
                "source_canonical": "Darcy",
                "aliases": ["Mr. Darcy"],
                "evidence_refs": ["evidence:darcy"],
                "source_unit_refs": [1],
                "source_block_refs": ["block:1"],
                "evidence": [
                    {
                        "evidence_id": "evidence:darcy",
                        "bounded_excerpt": "Darcy returns.",
                    }
                ],
                "confidence": 0.91,
                "category": "name",
            }
        ],
    }
    return PreparedGlossaryProviderRequest(
        packet=packet,
        metadata={"status": "provider_requested"},
    )


if __name__ == "__main__":
    unittest.main()
