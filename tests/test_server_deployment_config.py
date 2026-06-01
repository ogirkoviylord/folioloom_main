import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ServerDeploymentConfigTest(unittest.TestCase):
    def test_compose_uses_host_var_mount_for_runtime_files(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("./var:/app/var", compose)
        self.assertIn("./var:/data", compose)
        self.assertNotIn("app-var:/app/var", compose)
        self.assertNotIn("app-var:", compose)

    def test_compose_restarts_runtime_services_unless_stopped(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        for service in ("api:", "bot:", "worker:", "postgres:", "redis:", "clamd:"):
            service_start = compose.index(f"  {service}")
            next_service = len(compose)
            service_headers = (
                "  api:",
                "  bot:",
                "  worker:",
                "  postgres:",
                "  redis:",
                "  clamd:",
            )
            for candidate in service_headers:
                candidate_index = compose.find(candidate, service_start + 1)
                if candidate_index != -1:
                    next_service = min(next_service, candidate_index)
            service_block = compose[service_start:next_service]
            self.assertIn("restart: unless-stopped", service_block)
            self.assertIn("logging: *default-logging", service_block)

    def test_compose_limits_docker_log_size(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("x-default-logging: &default-logging", compose)
        self.assertIn('max-size: "10m"', compose)
        self.assertIn('max-file: "5"', compose)

    def test_compose_has_healthchecks_for_backend_services(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("x-default-healthcheck: &default-healthcheck", compose)
        self.assertIn("http.client.HTTPConnection('127.0.0.1', 8000", compose)
        self.assertIn("pg_isready", compose)
        self.assertIn("redis-cli", compose)
        self.assertIn("ping", compose)
        self.assertIn("clamdscan", compose)
        self.assertIn("--ping=1", compose)

    def test_compose_has_internal_only_clamd_service(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        service_start = compose.index("  clamd:")
        next_service = compose.find("\nvolumes:", service_start)
        clamd_block = compose[service_start:next_service]

        self.assertIn("image: ${CLAMD_IMAGE:-clamav/clamav:1.4}", clamd_block)
        self.assertIn("platform: ${CLAMD_PLATFORM:-linux/amd64}", clamd_block)
        self.assertIn('expose:\n      - "3310"', clamd_block)
        self.assertIn("clamav-db:/var/lib/clamav", clamd_block)
        self.assertIn("mem_limit: ${CLAMD_MEM_LIMIT:-2g}", clamd_block)
        self.assertNotIn("CLAMD_MEM_LIMIT:-1g", clamd_block)
        self.assertIn('cpus: "${CLAMD_CPUS:-1.0}"', clamd_block)
        self.assertIn("pids_limit: 256", clamd_block)
        self.assertNotIn("ports:", clamd_block)
        self.assertNotIn("3310:3310", clamd_block)
        self.assertIn("clamav-db:", compose)

    def test_server_env_example_has_production_runtime_keys(self):
        content = (ROOT / ".env.server.example").read_text(encoding="utf-8")

        required_lines = [
            "ENVIRONMENT=production",
            'SERVICE_NAME="FolioLoom"',
            "SCHEDULER_BACKEND=postgres",
            "SCHEDULER_MAX_ACTIVE_UNITS_GLOBAL=2",
            "SCHEDULER_MAX_ACTIVE_UNITS_PER_USER=1",
            "SCHEDULER_MAX_ACTIVE_JOBS_PER_USER=1",
            "SCHEDULER_MAX_ACTIVE_UNITS_PER_JOB=1",
            "SCHEDULER_PRIORITY_AGING_SECONDS=1800",
            "TRANSLATION_MAX_PARALLEL_UNITS=2",
            "DEEPSEEK_CHANNEL_COOLDOWN_SECONDS=30",
            "DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS=300",
            "DEEPSEEK_CHANNEL_COOLDOWN_JITTER_FRACTION=0.20",
            "DEEPSEEK_ADAPTIVE_THROTTLING_ENABLED=true",
            "DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL=1",
            "DEEPSEEK_ADAPTIVE_MIN_PARALLEL=1",
            "DEEPSEEK_ADAPTIVE_SUCCESS_RAMP_INTERVAL=8",
            "DEEPSEEK_ADAPTIVE_DECREASE_FACTOR=0.5",
            "DEEPSEEK_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=5",
            "DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS=120",
            "POSTGRES_PASSWORD=change-me",
            "POSTGRES_DSN=postgresql://translator:change-me@postgres:5432/translator",
            "DATABASE_URL=postgresql://translator:change-me@postgres:5432/translator",
            "REDIS_URL=redis://redis:6379/0",
            "OBJECT_STORAGE_ROOT=/data/object-storage",
            "PERSISTENT_JOBS_DB_PATH=/data/runtime/jobs.sqlite3",
            "USER_SETTINGS_DB_PATH=/data/runtime/user-settings.sqlite3",
            "TRANSLATION_RUN_LOG_ROOT=/data/run-logs",
            "REQUIRE_UPLOAD_SCAN=true",
            "UPLOAD_SCANNER_BACKEND=clamd",
            "UPLOAD_SCAN_MAX_CONCURRENCY=1",
            "UPLOAD_SCAN_BACKPRESSURE_TIMEOUT_SECONDS=1.0",
            "CLAMD_IMAGE=clamav/clamav:1.4",
            "CLAMD_PLATFORM=linux/amd64",
            "CLAMD_HOST=clamd",
            "CLAMD_PORT=3310",
            "CLAMD_TIMEOUT_SECONDS=10.0",
            "CLAMD_CHUNK_SIZE_BYTES=65536",
            "CLAMD_RESPONSE_LIMIT_BYTES=4096",
            "CLAMD_STARTUP_TIMEOUT=1800",
            "CLAMD_MEM_LIMIT=2g",
            "CLAMD_CPUS=1.0",
            "ADMIN_DB_PATH=/data/runtime/admin.sqlite3",
            "ADMIN_SESSION_SECRET=",
            "ADMIN_OWNER_PASSWORD=",
            "ADMIN_SECRET_MASTER_KEY=",
            "ADMIN_COOKIE_SECURE=false",
            "ADMIN_PROVIDER_RUNTIME_RELOAD_SECONDS=30",
        ]
        for line in required_lines:
            self.assertIn(line, content)

    def test_env_server_example_documents_beta_safety_caps(self):
        content = (ROOT / ".env.server.example").read_text(encoding="utf-8")

        required_lines = [
            "BETA_TRANSLATIONS_PAUSED=false",
            "BETA_GLOBAL_DAILY_COST_CAP_USD=5.00",
            "BETA_GLOBAL_MONTHLY_COST_CAP_USD=50.00",
            "BETA_USER_DAILY_COST_CAP_USD=1.00",
            "BETA_USER_MONTHLY_COST_CAP_USD=10.00",
            "BETA_USER_DAILY_JOB_LIMIT=3",
            "BETA_MAX_JOB_ESTIMATED_COST_USD=2.00",
            "BETA_COST_INPUT_USD_PER_MILLION=0.28",
            "BETA_COST_OUTPUT_USD_PER_MILLION=1.10",
            "BETA_COST_WARNING_FRACTION=0.80",
        ]
        for line in required_lines:
            self.assertIn(line, content)

    def test_server_operator_scripts_exist(self):
        deploy_script = ROOT / "scripts" / "deploy_server.sh"
        predeploy_script = ROOT / "scripts" / "predeploy_check.sh"
        smoke_script = ROOT / "scripts" / "server_smoke_check.sh"
        status_script = ROOT / "scripts" / "server_status.sh"
        verify_backup_script = ROOT / "scripts" / "verify_backup_export.py"

        self.assertTrue(deploy_script.exists())
        self.assertTrue(predeploy_script.exists())
        self.assertTrue(smoke_script.exists())
        self.assertTrue(status_script.exists())
        self.assertTrue(verify_backup_script.exists())
        self.assertIn("git pull --ff-only", deploy_script.read_text(encoding="utf-8"))
        self.assertIn(
            "scripts/server_smoke_check.sh",
            deploy_script.read_text(encoding="utf-8"),
        )

        predeploy_content = predeploy_script.read_text(encoding="utf-8")
        self.assertIn(
            "docker compose --env-file .env.server.example config",
            predeploy_content,
        )
        self.assertIn("tests.test_server_deployment_config", predeploy_content)
        self.assertIn("tests.test_backup_server_data", predeploy_content)
        self.assertIn("tests.test_admin_deployment_smoke", predeploy_content)
        self.assertIn("tests.test_admin_translation_logs", predeploy_content)
        self.assertIn("tests.test_clamd_runtime", predeploy_content)
        self.assertIn("tests.test_document_scanner", predeploy_content)
        self.assertIn(
            "test_admin_deepseek_translator_adds_admin_without_dropping_env",
            predeploy_content,
        )
        self.assertIn("translator_service.clamd_runtime --help", predeploy_content)
        self.assertIn("scripts/verify_backup_export.py --help", predeploy_content)
        self.assertIn("ruff check", predeploy_content)
        self.assertIn("git diff --check", predeploy_content)

        smoke_content = smoke_script.read_text(encoding="utf-8")
        self.assertIn("SCHEDULER_BACKEND", smoke_content)
        self.assertIn("postgres", smoke_content)
        self.assertIn("docker compose ps", smoke_content)
        self.assertIn("POSTGRES_PASSWORD=translator", smoke_content)
        self.assertIn("UPLOAD_SCANNER_BACKEND=clamd", smoke_content)
        self.assertIn("translator_service.clamd_runtime", smoke_content)
        self.assertIn("from translator_service.config import Settings", smoke_content)
        self.assertIn("app_require_upload_scan", smoke_content)
        self.assertIn("app_upload_scanner_backend", smoke_content)
        self.assertIn("clamd_host", smoke_content)
        self.assertIn("--scan-eicar", smoke_content)
        self.assertNotIn(
            'if [ "${REQUIRE_UPLOAD_SCAN:-false}" = "true" ]; then\n'
            '  set -- "$@" --scan-eicar',
            smoke_content,
        )
        self.assertIn("ADMIN_SMOKE_REQUIRE_PROVIDER_KEYS", smoke_content)
        self.assertIn(
            "docker compose exec -T api python -m "
            "translator_service.admin.deployment_smoke",
            smoke_content,
        )
        self.assertIn(
            "docker compose exec -T bot python -m "
            "translator_service.admin.deployment_smoke",
            smoke_content,
        )
        self.assertIn(
            "docker compose exec -T worker python -m "
            "translator_service.admin.deployment_smoke",
            smoke_content,
        )

        status_content = status_script.read_text(encoding="utf-8")
        self.assertIn("df -h", status_content)
        self.assertIn("du -sh var", status_content)
        self.assertIn("docker compose logs --tail=200 bot", status_content)
        self.assertIn("folioloom_exports", status_content)

    def test_restore_runbook_documents_backup_rehearsal(self):
        content = (ROOT / "docs" / "deployment" / "restore-runbook.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("scripts/verify_backup_export.py", content)
        self.assertIn("docker compose down", content)
        self.assertIn("docker compose exec -T postgres psql", content)
        self.assertIn("tar xzf", content)
        self.assertIn("var/runtime/admin.sqlite3", content)
        self.assertIn("--require-admin-provider-keys", content)

    def test_vps_runbook_matches_host_var_deploy_model(self):
        content = (ROOT / "docs" / "deployment" / "admin-vps-runbook.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("cp .env.server.example .env", content)
        self.assertIn("ENVIRONMENT=production", content)
        self.assertIn("./var", content)
        self.assertIn("/data/runtime/admin.sqlite3", content)
        self.assertIn("/data/run-logs", content)
        self.assertNotIn("app-var", content)

    def test_admin_runtime_dependencies_are_production_dependencies(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = pyproject["project"]["dependencies"]

        self.assertTrue(
            any(dependency.startswith("httpx") for dependency in dependencies),
            "admin provider probe imports httpx at API startup, "
            "so httpx must not be dev-only",
        )


if __name__ == "__main__":
    unittest.main()
