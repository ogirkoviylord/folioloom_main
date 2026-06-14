import json
import tempfile
import unittest
from pathlib import Path

from tools.glossary_runtime_provider_smoke import (
    APPROVED_INPUT_TARGETS,
    APPROVED_OWNER_TEST_INPUT_TARGETS,
    DEFAULT_DIAGNOSTIC_ROOT,
    DEFAULT_MODEL,
    DEFAULT_TARGET_METADATA_FIXTURE_PATH,
    ISSUE_507_ID,
    ISSUE_507_MAX_CALLS,
    FakeRuntimeProvider,
    RuntimePackageSelectionError,
    RuntimeSmokePackage,
    SmokeConfig,
    apply_runtime_pressure_fallback,
    build_epub_runtime_unit_selection_decision,
    build_glossary_off_runtime_package,
    build_runtime_glossary_budget_plan,
    build_runtime_package,
    build_runtime_pressure_fallback_decision,
    build_runtime_pressure_summary,
    build_runtime_prompt,
    format_runtime_glossary_prompt_context,
    run_fake_paired_epub_rehearsal,
    run_smoke,
    select_epub_runtime_unit_for_rehearsal,
    validate_runtime_response,
)


def _synthetic_runtime_package(
    *,
    document_format: str = "epub",
    source_block_count: int = 58,
    raw_source: str = "RAW SOURCE SENTENCE MUST NOT SERIALIZE",
    protected_text: str = "{{PH_1}} {{PH_2}}",
    required_markers: tuple[tuple[str, ...], ...] = (("{{PH_1}}",), ("{{PH_2}}",)),
) -> RuntimeSmokePackage:
    return RuntimeSmokePackage(
        input_path=Path(f"/tmp/synthetic.{document_format}"),
        input_id=f"synthetic-{document_format}-ru",
        target_language="ru",
        document_format=document_format,
        fragment_count=1,
        character_count=12_000,
        unit_sequence=1,
        source_block_ids=tuple(
            f"block:v1:{index}" for index in range(source_block_count)
        ),
        source_text=raw_source,
        protected_text=protected_text,
        required_markers=required_markers,
        glossary_plan={
            "status": "planned",
            "fallback_reason": "none",
            "work_unit_plans": [
                {
                    "work_unit_sequence": 1,
                    "fallback_reason_codes": ["prompt_budget_exhausted"],
                }
            ],
        },
        adapter_metadata={
            "status": "ready",
            "selected_entry_ids": ["entry-1", "entry-2"],
            "cache_policy": {
                "behavior": "bypass_glossary_injected_cache",
                "cache_get_allowed": False,
                "cache_put_allowed": False,
            },
            "work_unit_selection_signature": "selection:v1:test",
        },
        prompt_context_text="<glossary_context>redacted</glossary_context>",
        prompt_context_metadata={
            "included_entry_ids": ["entry-1", "entry-2"],
            "included_entries": [
                {
                    "entry_id": "entry-1",
                    "estimated_prompt_tokens": 100,
                    "character_count": 300,
                    "field_omissions": [],
                },
                {
                    "entry_id": "entry-2",
                    "estimated_prompt_tokens": 120,
                    "character_count": 360,
                    "field_omissions": [],
                },
            ],
            "omitted_entries": [
                {"entry_id": "entry-3", "reason": "prompt_budget_exhausted"}
            ],
            "estimated_prompt_tokens": 837,
            "character_count": 2_400,
        },
        selection_metadata={
            "dropped_entries": [
                {"entry_id": "entry-3", "reason": "prompt_budget_exhausted"}
            ],
            "budget_exceeded": False,
            "estimated_prompt_tokens": 360,
        },
        glossary_entry_count=12,
        glossary_evidence_count=34,
        reducer_metadata={"diagnostic_count": 3, "dropped_count": 91},
    )


def _runtime_context_entry(
    entry_id: str,
    *,
    source: str,
    target: str,
) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "layer": "soft",
        "category": "name",
        "status": "validator_accepted",
        "source_canonical": source,
        "target_canonical": target,
        "strategy": "transliterate",
        "confidence": 0.9,
    }


class GlossaryRuntimeProviderSmokeTest(unittest.TestCase):
    def test_fake_smoke_writes_metadata_report_without_raw_prompt_text(self):
        fixture = Path("test_samples/sample_book.en.txt")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "report.md"
            config = SmokeConfig(
                input_targets=((fixture, "ru"),),
                diagnostic_root=tmp_path / "diagnostics",
                fake=True,
            )

            report = run_smoke(
                config,
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
                metadata_report_path=report_path,
            )

            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["calls_made"], 1)
            self.assertEqual(report["calls"][0]["status"], "validated")
            self.assertTrue(report_path.is_file())
            rendered = report_path.read_text(encoding="utf-8")
            source_text = fixture.read_text(encoding="utf-8")
            self.assertNotIn(source_text[:40], rendered)
            self.assertNotIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", rendered)
            self.assertNotIn("provider_response", rendered)
            self.assertIn("Validation issue codes", rendered)
            self.assertIn("| none |", rendered)
            self.assertIn("Runtime Pressure Summary", rendered)
            pressure = report["calls"][0]["pressure_summary"]
            self.assertFalse(pressure["raw_payload_included"])
            self.assertEqual(
                pressure["cache_policy"]["behavior"],
                "bypass_glossary_injected_cache",
            )
            self.assertNotIn(
                source_text[:40],
                json.dumps(pressure, ensure_ascii=False, sort_keys=True),
            )
            diagnostic_dir = Path(report["diagnostic_dir"])
            self.assertTrue((diagnostic_dir / "manifest.json").is_file())
            call_files = sorted(diagnostic_dir.glob("call-*.json"))
            self.assertEqual(len(call_files), 1)
            diagnostic = json.loads(call_files[0].read_text(encoding="utf-8"))
            self.assertIn("user_prompt", diagnostic)
            self.assertIn("response_text", diagnostic)
            self.assertFalse(
                diagnostic["access_boundary"]["github_issue_or_pr_allowed"]
            )

    def test_rejects_unapproved_caps_and_targets_for_live_boundary(self):
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(max_calls=6, fake=True),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(
                    input_targets=((Path("test_samples/sample_book.en.txt"), "uk"),),
                    fake=True,
                ),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(provider_base_url="https://example.invalid", fake=True),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )

    def test_live_boundary_defaults_match_approved_issue_values(self):
        config = SmokeConfig()

        self.assertEqual(config.input_targets, APPROVED_INPUT_TARGETS)
        self.assertEqual(config.diagnostic_root, DEFAULT_DIAGNOSTIC_ROOT)
        self.assertEqual(config.provider_model, DEFAULT_MODEL)
        self.assertEqual(config.max_calls, 5)
        self.assertEqual(config.max_tokens_total, 50_000)
        self.assertTrue(config.raw_text_capture)

    def test_issue_507_control_epub_fake_smoke_runs_paired_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "issue-507-report.md"
            config = SmokeConfig(
                issue_id=ISSUE_507_ID,
                input_targets=APPROVED_OWNER_TEST_INPUT_TARGETS,
                diagnostic_root=tmp_path / "diagnostics",
                max_calls=ISSUE_507_MAX_CALLS,
                fake=True,
                target_metadata_fixture_path=DEFAULT_TARGET_METADATA_FIXTURE_PATH,
                paired_glossary_off=True,
            )

            report = run_smoke(
                config,
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
                metadata_report_path=report_path,
            )

            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["approval"]["issue_id"], "507")
            self.assertEqual(report["approval"]["max_calls"], 4)
            self.assertTrue(report["approval"]["paired_glossary_off"])
            self.assertEqual(report["calls_made"], 4)
            self.assertIn(
                "live_provider_behavior_unknown",
                report["recommendation"],
            )
            self.assertIn(
                "live provider behavior is Unknown",
                " ".join(report["unknown"]),
            )
            self.assertIn(
                "fake provider stub responses passed local validation",
                report["confirmed"],
            )
            self.assertEqual(
                [call["side"] for call in report["calls"]],
                [
                    "glossary_on",
                    "glossary_off",
                    "glossary_on",
                    "glossary_off",
                ],
            )
            self.assertEqual(
                [call["target_language"] for call in report["calls"]],
                ["ru", "ru", "uk", "uk"],
            )
            self.assertTrue(
                all(call["status"] == "validated" for call in report["calls"])
            )
            self.assertEqual(
                report["calls"][0]["adapter"]["cache_policy"]["behavior"],
                "bypass_glossary_injected_cache",
            )
            self.assertEqual(
                report["calls"][1]["adapter"]["cache_policy"]["behavior"],
                "default_runtime_cache",
            )
            rendered = report_path.read_text(encoding="utf-8")
            self.assertNotIn("<translation_batch>", rendered)
            self.assertNotIn("<glossary_context", rendered)
            self.assertNotIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", rendered)

    def test_issue_507_boundary_rejects_missing_pairing_or_wrong_live_root(self):
        base_config = {
            "issue_id": ISSUE_507_ID,
            "input_targets": APPROVED_OWNER_TEST_INPUT_TARGETS,
            "max_calls": ISSUE_507_MAX_CALLS,
            "target_metadata_fixture_path": DEFAULT_TARGET_METADATA_FIXTURE_PATH,
            "paired_glossary_off": True,
        }

        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(
                    **{
                        **base_config,
                        "paired_glossary_off": False,
                        "fake": True,
                    }
                ),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(
                    **{
                        **base_config,
                        "max_calls": ISSUE_507_MAX_CALLS + 1,
                        "fake": True,
                    }
                ),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )
        with self.assertRaises(ValueError):
            run_smoke(
                SmokeConfig(
                    **{
                        **base_config,
                        "diagnostic_root": DEFAULT_DIAGNOSTIC_ROOT,
                        "fake": False,
                    }
                ),
                provider=FakeRuntimeProvider(),
                repo_root=Path.cwd(),
            )

    def test_pressure_summary_distinguishes_epub_shape_without_raw_text(self):
        raw_source = "RAW SOURCE SENTENCE MUST NOT SERIALIZE"
        package = _synthetic_runtime_package(raw_source=raw_source)

        summary = build_runtime_pressure_summary(
            package,
            config=SmokeConfig(fake=True),
            estimated_prompt_tokens=4_500,
            reserved_tokens=10_800,
        )

        self.assertEqual(summary["unit"]["source_block_id_count"], 58)
        self.assertEqual(summary["unit"]["protected_marker_count"], 2)
        self.assertEqual(summary["unit"]["source_character_count"], len(raw_source))
        self.assertEqual(summary["glossary"]["selected_entry_count"], 2)
        self.assertEqual(summary["tokens"]["estimated_request_prompt_tokens"], 4_500)
        self.assertEqual(summary["tokens"]["reserved_request_tokens"], 10_800)
        self.assertEqual(
            summary["output_contract"]["risk_category"],
            "epub_multi_block_with_protected_markers",
        )
        self.assertIn(
            "prompt_budget_exhausted",
            summary["fallback"]["work_unit_fallback_reason_codes"],
        )
        serialized = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn("{{PH_1}}", serialized)
        self.assertNotIn("<glossary_context", serialized)

    def test_pressure_fallback_omits_context_for_high_pressure_epub_unit(self):
        raw_source = "RAW EPUB SOURCE MUST NOT SERIALIZE"
        package = _synthetic_runtime_package(raw_source=raw_source)

        degraded = apply_runtime_pressure_fallback(
            package,
            config=SmokeConfig(fake=True),
        )
        summary = build_runtime_pressure_summary(
            degraded,
            config=SmokeConfig(fake=True),
        )
        _, _, request_text = build_runtime_prompt(degraded)

        self.assertEqual(degraded.prompt_context_text, "")
        self.assertNotIn("<glossary_context", request_text)
        self.assertEqual(degraded.prompt_context_metadata["included_entry_ids"], [])
        self.assertEqual(degraded.prompt_context_metadata["estimated_prompt_tokens"], 0)
        self.assertEqual(
            degraded.adapter_metadata["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        pressure_fallback = degraded.prompt_context_metadata["pressure_fallback"]
        self.assertEqual(
            pressure_fallback["action"],
            "omit_glossary_prompt_context",
        )
        self.assertIn(
            "epub_source_block_count_exceeds_limit",
            pressure_fallback["reason_codes"],
        )
        self.assertEqual(
            summary["fallback"]["pressure_fallback_action"],
            "omit_glossary_prompt_context",
        )
        self.assertIn(
            "high_pressure_epub_runtime_fallback",
            summary["fallback"]["prompt_context_omission_reasons"],
        )
        serialized = json.dumps(
            {
                "decision": pressure_fallback,
                "metadata": degraded.prompt_context_metadata,
                "summary": summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn("{{PH_1}}", serialized)
        self.assertNotIn("<glossary_context", serialized)

    def test_pressure_fallback_keeps_low_pressure_txt_like_context_eligible(self):
        package = _synthetic_runtime_package(
            document_format="txt",
            source_block_count=1,
            raw_source="Short safe source text.",
            protected_text="Short safe source text.",
            required_markers=(),
        )

        decision = build_runtime_pressure_fallback_decision(
            package,
            config=SmokeConfig(fake=True),
        )
        kept = apply_runtime_pressure_fallback(package, config=SmokeConfig(fake=True))

        self.assertEqual(decision["action"], "keep_glossary_prompt_context")
        self.assertEqual(decision["reason_codes"], [])
        self.assertEqual(kept.prompt_context_text, package.prompt_context_text)
        self.assertEqual(
            kept.prompt_context_metadata["included_entry_ids"],
            ["entry-1", "entry-2"],
        )

    def test_epub_unit_selector_selects_small_glossary_useful_unit(self):
        package = _synthetic_runtime_package(
            source_block_count=1,
            raw_source="Darcy returns quietly.",
            protected_text="Darcy returns quietly.",
            required_markers=(),
        )
        useful_entry = _runtime_context_entry(
            "entry-1",
            source="Fitzwilliam Darcy",
            target="Дарси",
        )
        useful_entry["aliases"] = ["Darcy"]
        entries = [
            useful_entry,
            _runtime_context_entry("entry-2", source="Elizabeth", target="Элизабет"),
        ]

        selected = select_epub_runtime_unit_for_rehearsal(
            [package],
            config=SmokeConfig(fake=True),
            entries=entries,
            input_id="synthetic-epub-ru",
            target_language="ru",
        )

        metadata = selected.prompt_context_metadata["epub_runtime_unit_selection"]
        self.assertEqual(metadata["status"], "selected")
        self.assertEqual(metadata["reason_codes"], [])
        self.assertEqual(metadata["glossary"]["useful_entry_ids"], ["entry-1"])
        self.assertEqual(
            metadata["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        pressure = build_runtime_pressure_summary(
            selected,
            config=SmokeConfig(fake=True),
        )
        self.assertEqual(
            pressure["epub_runtime_unit_selection"]["status"],
            "selected",
        )
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Darcy returns quietly.", serialized)
        self.assertNotIn("Дарси", serialized)
        self.assertNotIn("<glossary_context", serialized)

    def test_epub_unit_selector_skips_missing_target_metadata(self):
        package = _synthetic_runtime_package(
            source_block_count=1,
            raw_source="Darcy returns quietly.",
            protected_text="Darcy returns quietly.",
            required_markers=(),
        )
        entries = [
            {
                **_runtime_context_entry("entry-1", source="Darcy", target=""),
                "target_canonical": "",
                "target_variants": [],
            }
        ]

        decision = build_epub_runtime_unit_selection_decision(
            package,
            config=SmokeConfig(fake=True),
            entries=entries,
        )

        self.assertEqual(decision["status"], "skipped")
        self.assertIn("target_metadata_missing", decision["reason_codes"])
        self.assertEqual(decision["glossary"]["source_match_entry_count"], 1)
        self.assertEqual(decision["glossary"]["useful_entry_count"], 0)
        serialized = json.dumps(decision, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Darcy returns quietly.", serialized)
        self.assertNotIn("<glossary_context", serialized)

    def test_epub_unit_selector_skips_high_pressure_unit_metadata_only(self):
        raw_source = "Darcy " + ("raw pressure text " * 50)
        package = _synthetic_runtime_package(
            source_block_count=58,
            raw_source=raw_source,
            protected_text="Darcy returns quietly.",
            required_markers=(),
        )
        entries = [_runtime_context_entry("entry-1", source="Darcy", target="Дарси")]

        decision = build_epub_runtime_unit_selection_decision(
            package,
            config=SmokeConfig(fake=True),
            entries=entries,
        )

        self.assertEqual(decision["status"], "skipped")
        self.assertIn(
            "epub_source_block_count_exceeds_limit",
            decision["reason_codes"],
        )
        self.assertEqual(
            decision["pressure_fallback"]["action"],
            "omit_glossary_prompt_context",
        )
        serialized = json.dumps(decision, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn("Дарси", serialized)
        self.assertNotIn("<translation_batch>", serialized)

    def test_epub_unit_selector_reports_no_eligible_fallback_metadata(self):
        raw_source = "Darcy returns quietly."
        package = _synthetic_runtime_package(
            source_block_count=1,
            raw_source=raw_source,
            protected_text=raw_source,
            required_markers=(),
        )
        entries = [_runtime_context_entry("entry-1", source="Wickham", target="Уикем")]

        with self.assertRaises(RuntimePackageSelectionError) as raised:
            select_epub_runtime_unit_for_rehearsal(
                [package],
                config=SmokeConfig(fake=True),
                entries=entries,
                input_id="synthetic-epub-ru",
                target_language="ru",
            )

        error = raised.exception
        self.assertEqual(error.code, "no_glossary_useful_pressure_safe_epub_unit")
        self.assertEqual(error.metadata["status"], "skipped_selection")
        self.assertEqual(
            error.metadata["fallback_action"],
            "use_glossary_off_local_rehearsal_metadata",
        )
        self.assertEqual(
            error.metadata["fallback_cache_policy"]["behavior"],
            "default_runtime_cache",
        )
        self.assertIn(
            "source_term_or_alias_absent",
            error.metadata["reason_codes"],
        )
        serialized = json.dumps(error.metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn("Уикем", serialized)
        self.assertNotIn("<glossary_context", serialized)

    def test_control_epub_target_metadata_fixture_enables_ru_uk_rehearsal(self):
        fixture = Path("test_samples/gutenberg_time_machine_noimages.en.epub")
        target_strings = {
            "ru": (
                "\u0442\u0440\u0438 "
                "\u0438\u0437\u043c\u0435\u0440\u0435\u043d\u0438\u044f"
            ),
            "uk": "\u0442\u0440\u0438 \u0432\u0438\u043c\u0456\u0440\u0438",
        }

        for target_language in ("ru", "uk"):
            with self.subTest(target_language=target_language):
                package = build_runtime_package(
                    fixture,
                    target_language,
                    config=SmokeConfig(
                        input_targets=((fixture, target_language),),
                        fake=True,
                        target_metadata_fixture_path=(
                            DEFAULT_TARGET_METADATA_FIXTURE_PATH
                        ),
                    ),
                    repo_root=Path.cwd(),
                )

                metadata = package.prompt_context_metadata[
                    "epub_runtime_unit_selection"
                ]
                fixture_metadata = metadata["target_metadata_fixture"]
                self.assertEqual(metadata["status"], "selected")
                self.assertEqual(metadata["reason_codes"], [])
                self.assertEqual(fixture_metadata["status"], "applied")
                self.assertEqual(fixture_metadata["fixture_entry_count"], 1)
                self.assertEqual(fixture_metadata["matched_entry_count"], 1)
                self.assertEqual(metadata["glossary"]["useful_entry_count"], 1)
                self.assertEqual(
                    package.adapter_metadata["cache_policy"]["behavior"],
                    "bypass_glossary_injected_cache",
                )
                self.assertIn(
                    target_strings[target_language],
                    package.prompt_context_text,
                )

                report = run_fake_paired_epub_rehearsal(
                    package,
                    config=SmokeConfig(
                        input_targets=((fixture, target_language),),
                        fake=True,
                        target_metadata_fixture_path=(
                            DEFAULT_TARGET_METADATA_FIXTURE_PATH
                        ),
                    ),
                    provider=FakeRuntimeProvider(),
                )
                self.assertEqual(report["status"], "completed")
                self.assertEqual(
                    report["pairs"]["glossary_on"]["cache_policy"]["behavior"],
                    "bypass_glossary_injected_cache",
                )
                self.assertEqual(
                    report["pairs"]["glossary_off"]["cache_policy"]["behavior"],
                    "default_runtime_cache",
                )

                serialized = json.dumps(
                    {
                        "selection": metadata,
                        "report": report,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                self.assertNotIn(target_strings[target_language], serialized)
                self.assertNotIn("three dimensions", serialized)
                self.assertNotIn("<glossary_context", serialized)
                self.assertNotIn("<translation_batch>", serialized)

    def test_control_epub_missing_target_metadata_fixture_falls_back_safely(self):
        fixture = Path("test_samples/gutenberg_time_machine_noimages.en.epub")

        with self.assertRaises(RuntimePackageSelectionError) as raised:
            build_runtime_package(
                fixture,
                "ru",
                config=SmokeConfig(
                    input_targets=((fixture, "ru"),),
                    fake=True,
                    target_metadata_fixture_path=Path(
                        "test_samples/glossary_targets/missing-fixture.json"
                    ),
                ),
                repo_root=Path.cwd(),
            )

        metadata = raised.exception.metadata
        self.assertIn("target_metadata_missing", metadata["reason_codes"])
        fixture_metadata = metadata["target_metadata_fixture"]
        self.assertEqual(fixture_metadata["status"], "missing")
        self.assertIn(
            "target_metadata_fixture_missing",
            fixture_metadata["reason_codes"],
        )
        self.assertEqual(
            metadata["fallback_cache_policy"]["behavior"],
            "default_runtime_cache",
        )
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("<glossary_context", serialized)
        self.assertNotIn("<translation_batch>", serialized)

    def test_control_epub_invalid_target_fixture_raw_field_is_rejected(self):
        fixture = Path("test_samples/gutenberg_time_machine_noimages.en.epub")
        with tempfile.TemporaryDirectory() as tmp:
            fixture_path = Path(tmp) / "invalid-target-fixture.json"
            fixture_path.write_text(
                json.dumps(
                    {
                        "schema_version": (
                            "glossary-runtime-target-metadata-fixture-v1"
                        ),
                        "fixture_id": "invalid-raw-field-fixture",
                        "input_path": str(fixture),
                        "source_language": "en",
                        "scope": "local_owner_only_epub_runtime_smoke",
                        "owner_approved": True,
                        "targets": {
                            "ru": {
                                "entries": [
                                    {
                                        "source_canonical": "three dimensions",
                                        "target_canonical": "RAW TARGET",
                                        "raw_source": (
                                            "RAW SOURCE MUST NOT SERIALIZE"
                                        ),
                                    }
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(RuntimePackageSelectionError) as raised:
                build_runtime_package(
                    fixture,
                    "ru",
                    config=SmokeConfig(
                        input_targets=((fixture, "ru"),),
                        fake=True,
                        target_metadata_fixture_path=fixture_path,
                    ),
                    repo_root=Path.cwd(),
                )

        metadata = raised.exception.metadata
        fixture_metadata = metadata["target_metadata_fixture"]
        self.assertEqual(fixture_metadata["status"], "invalid")
        self.assertIn(
            "target_metadata_fixture_raw_field_present",
            fixture_metadata["reason_codes"],
        )
        self.assertIn("target_metadata_missing", metadata["reason_codes"])
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("RAW SOURCE MUST NOT SERIALIZE", serialized)
        self.assertNotIn("RAW TARGET", serialized)
        self.assertNotIn("<glossary_context", serialized)

    def test_epub_budget_plan_reduces_context_and_preserves_escaping(self):
        plan = build_runtime_glossary_budget_plan(
            document_format="epub",
            source_block_count=6,
            protected_marker_count=0,
            protected_text="Short protected text.",
            config=SmokeConfig(fake=True),
        )
        text, metadata = format_runtime_glossary_prompt_context(
            [
                _runtime_context_entry(
                    "entry:darcy",
                    source='Darcy <ignore role="system">',
                    target="Дарси & co",
                )
            ],
            selected_entry_ids=("entry:darcy",),
            budget_plan=plan,
        )

        self.assertEqual(plan["policy"], "epub_completion_first_pressure_budget")
        self.assertLess(
            plan["prompt_context"]["max_prompt_tokens"],
            1_200,
        )
        self.assertLessEqual(plan["selection"]["max_prompt_tokens"], 360)
        self.assertIn("epub_multi_source_block_unit", plan["reason_codes"])
        self.assertIn("<glossary_context", text)
        self.assertIn("Darcy &lt;ignore role=\"system\"&gt;", text)
        self.assertIn("Дарси &amp; co", text)
        self.assertEqual(metadata["runtime_budget"]["policy"], plan["policy"])
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn('Darcy <ignore role="system">', serialized)
        self.assertNotIn("Дарси & co", serialized)

    def test_epub_budget_plan_can_omit_context_without_raw_metadata(self):
        raw_source = "RAW COMPLETION PRESSURE SOURCE MUST NOT SERIALIZE"
        raw_target = "RAW TARGET MUST NOT SERIALIZE"
        plan = build_runtime_glossary_budget_plan(
            document_format="epub",
            source_block_count=6,
            protected_marker_count=2,
            protected_text="x" * 8_000,
            config=SmokeConfig(fake=True),
        )
        text, metadata = format_runtime_glossary_prompt_context(
            [
                _runtime_context_entry(
                    "entry:pressure",
                    source=raw_source,
                    target=raw_target,
                )
            ],
            selected_entry_ids=("entry:pressure",),
            budget_plan=plan,
        )

        self.assertEqual(text, "")
        self.assertLess(plan["selection"]["max_prompt_tokens"], 360)
        self.assertGreater(plan["selection"]["max_prompt_tokens"], 0)
        self.assertEqual(plan["prompt_context"]["max_entries"], 0)
        self.assertIn("glossary_context_budget_omitted", plan["reason_codes"])
        self.assertEqual(metadata["runtime_budget"]["policy"], plan["policy"])
        self.assertFalse(metadata["runtime_budget"]["raw_payload_included"])
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn(raw_target, serialized)
        self.assertNotIn("<glossary_context", serialized)

    def test_fake_paired_epub_rehearsal_reports_metadata_only_baseline(self):
        raw_source = "RAW EPUB PAIRED SOURCE MUST NOT SERIALIZE"
        package = apply_runtime_pressure_fallback(
            _synthetic_runtime_package(raw_source=raw_source),
            config=SmokeConfig(fake=True),
        )

        report = run_fake_paired_epub_rehearsal(
            package,
            config=SmokeConfig(fake=True),
            provider=FakeRuntimeProvider(),
        )

        self.assertEqual(
            report["schema_version"],
            "glossary-runtime-paired-rehearsal-v1",
        )
        self.assertEqual(report["status"], "completed")
        self.assertFalse(report["live_provider_calls_allowed"])
        self.assertFalse(report["quality_claims_made"])
        glossary_on = report["pairs"]["glossary_on"]
        glossary_off = report["pairs"]["glossary_off"]
        self.assertEqual(glossary_on["status"], "validated")
        self.assertEqual(glossary_off["status"], "validated")
        self.assertEqual(
            glossary_on["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        self.assertEqual(
            glossary_off["cache_policy"]["behavior"],
            "default_runtime_cache",
        )
        self.assertEqual(
            glossary_on["prompt_context"]["pressure_fallback_action"],
            "omit_glossary_prompt_context",
        )
        self.assertEqual(glossary_off["prompt_context"]["included_entry_count"], 0)
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", serialized)
        self.assertNotIn("<translation_batch>", serialized)

    def test_glossary_off_runtime_package_keeps_default_cache_metadata(self):
        package = _synthetic_runtime_package(document_format="epub")

        baseline = build_glossary_off_runtime_package(package)

        self.assertEqual(baseline.prompt_context_text, "")
        self.assertEqual(baseline.adapter_metadata["status"], "disabled")
        self.assertEqual(
            baseline.adapter_metadata["cache_policy"]["behavior"],
            "default_runtime_cache",
        )
        self.assertTrue(baseline.adapter_metadata["cache_policy"]["cache_get_allowed"])
        self.assertTrue(baseline.adapter_metadata["cache_policy"]["cache_put_allowed"])

    def test_fake_paired_epub_rehearsal_rejects_non_fake_provider(self):
        class NotFakeProvider:
            pass

        with self.assertRaises(ValueError):
            run_fake_paired_epub_rehearsal(
                _synthetic_runtime_package(document_format="epub"),
                config=SmokeConfig(fake=True),
                provider=NotFakeProvider(),  # type: ignore[arg-type]
            )

    def test_package_builds_glossary_injected_runtime_prompt(self):
        package = build_runtime_package(
            Path("test_samples/sample_book.en.txt"),
            "ru",
            config=SmokeConfig(
                input_targets=((Path("test_samples/sample_book.en.txt"), "ru"),),
                fake=True,
            ),
            repo_root=Path.cwd(),
        )
        system_prompt, user_prompt, request_text = build_runtime_prompt(package)

        self.assertEqual(package.adapter_metadata["status"], "ready")
        self.assertEqual(
            package.adapter_metadata["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        self.assertIn("<glossary_context", request_text)
        self.assertIn("<translation_batch>", request_text)
        self.assertIn("BEGIN_UNTRUSTED_DOCUMENT_CONTENT", user_prompt)
        self.assertIn("professional document translator", system_prompt)

    def test_validation_rejects_malformed_provider_output(self):
        package = build_runtime_package(
            Path("test_samples/sample_book.en.txt"),
            "ru",
            config=SmokeConfig(
                input_targets=((Path("test_samples/sample_book.en.txt"), "ru"),),
                fake=True,
            ),
            repo_root=Path.cwd(),
        )
        result = FakeRuntimeProvider().chat(
            model="deepseek-v4-pro",
            system_prompt="system",
            user_prompt=(
                '<translation_batch><translation_block id="0">x'
                "</translation_block></translation_batch>"
            ),
            max_completion_tokens=100,
        )
        malformed = type(result)(
            ok=True,
            content="not xml",
            usage=result.usage,
            finish_reason="stop",
            http_status=200,
            elapsed_seconds=0,
            request_payload=result.request_payload,
        )

        validation = validate_runtime_response(malformed, package=package)

        self.assertFalse(validation["valid"])
        self.assertIn("external_text", validation["issue_codes"])


if __name__ == "__main__":
    unittest.main()
