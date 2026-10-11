"""Check deployment isolation and fail-closed configuration without starting services."""

import base64
import json
import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from oria_engine.config import Settings

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    "ORIA_APP_IMAGE",
    "ORIA_ASTROLOGY_IMAGE",
    "POSTGRES_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_WEBHOOK_BASE_URL",
    "PROFILE_ENCRYPTION_KEY",
    "SECOND_CONTEXT_BEARER_TOKEN",
)


@pytest.fixture
def deployment_env():
    # Compose never reads the operator's .env and every interpolated setting is explicit.
    return {
        "PATH": os.environ["PATH"],
        "ORIA_APP_IMAGE": "quay.io/bdobrica/oria-engine:9.8.7",
        "ORIA_ASTROLOGY_IMAGE": "quay.io/bdobrica/oria-astrology-mcp@sha256:" + "a" * 64,
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "POSTGRES_ADMIN_PASSWORD": secrets.token_hex(24),
        "POSTGRES_PASSWORD_URLENCODED": "",
        "GATEWAY_PORT": "8001",
        "LOG_LEVEL": "INFO",
        "TELEGRAM_BOT_TOKEN": "123456:" + secrets.token_hex(24),
        "TELEGRAM_WEBHOOK_SECRET": secrets.token_hex(24),
        "TELEGRAM_WEBHOOK_BASE_URL": "https://oria.example.invalid",
        "PROFILE_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "PROFILE_ENCRYPTION_KEY_VERSION": "v1",
        "ORIA_POLICY_VERSION": "2026-10-03.2",
        "SECOND_CONTEXT_BASE_URL": "http://context.example.invalid:8080",
        "SECOND_CONTEXT_BEARER_TOKEN": secrets.token_hex(24),
        "SECOND_CONTEXT_IMAGE": "quay.io/bdobrica/secondcontext-gateway:0.1.1",
        "SECOND_CONTEXT_POSTGRES_PASSWORD": secrets.token_hex(24),
        "SECOND_CONTEXT_OPENAI_API_KEY": secrets.token_hex(24),
        "SECOND_CONTEXT_OPENAI_BASE_URL": "https://api.openai.com/v1",
        "SECOND_CONTEXT_CHAT_MODEL": "gpt-4.1-mini",
        "SECOND_CONTEXT_EMBEDDING_MODEL": "text-embedding-3-small",
        "SECOND_CONTEXT_VECTOR_SIZE": "1536",
        "INBOUND_RATE_PER_MINUTE": "20",
        "QUEUED_JOBS_PER_USER": "8",
        "LLM_PROCESSING_ENABLED": "true",
    }


def render(environment, *, bundled=False):
    filename = "compose.full.yaml" if bundled else "compose.oria.yaml"
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-p",
            "oria-deployment-config-test",
            "-f",
            str(ROOT / "deploy" / filename),
            "config",
            "--format",
            "json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_deployment_security_boundaries(deployment_env):
    result = render(deployment_env)
    assert result.returncode == 0, "Synthetic deployment configuration failed"
    config = json.loads(result.stdout)
    services = config["services"]
    assert set(services) == {"postgres", "redis", "astrology-mcp", "migrate", "gateway", "worker"}
    for name, service in services.items():
        assert "build" not in service and "env_file" not in service
        assert "ports" not in service or name == "gateway"
    assert services["gateway"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert config["networks"]["storage"]["internal"]
    assert config["networks"]["astrology"]["internal"]
    assert set(services["postgres"]["networks"]) == {"storage"}
    assert set(services["redis"]["networks"]) == {"storage"}
    assert set(services["astrology-mcp"]["networks"]) == {"astrology"}
    assert "environment" not in services["astrology-mcp"]
    assert set(services["migrate"]["environment"]) == {"APP_ENV", "DATABASE_URL"}
    assert set(services["migrate"]["networks"]) == {"storage"}
    assert "volumes" not in services["gateway"] and "volumes" not in services["worker"]
    for name in ("gateway", "worker", "migrate"):
        assert services[name]["image"] == deployment_env["ORIA_APP_IMAGE"]
    assert services["astrology-mcp"]["image"] == deployment_env["ORIA_ASTROLOGY_IMAGE"]
    for name in ("gateway", "worker"):
        settings = Settings(
            _env_file=None,
            **{key.lower(): value for key, value in services[name]["environment"].items()},
        )
        assert settings.app_env == "production"
        assert settings.second_context_subject_namespace == "oria"
        assert (
            services[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
        )
        assert not {"OPENAI_API_KEY", "QUAY_AUTH"} & services[name]["environment"].keys()


@pytest.mark.parametrize("missing", REQUIRED)
def test_missing_deployment_configuration_fails_closed(deployment_env, missing):
    deployment_env.pop(missing)
    result = render(deployment_env)
    assert result.returncode != 0
    assert not result.stdout
    assert missing in result.stderr
    for name in ("TELEGRAM_BOT_TOKEN", "PROFILE_ENCRYPTION_KEY", "SECOND_CONTEXT_BEARER_TOKEN"):
        if name in deployment_env:
            assert deployment_env[name] not in result.stderr


def test_template_covers_deployment_configuration(deployment_env):
    names = {
        line.split("=", 1)[0]
        for line in (ROOT / "deploy/.env.example").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert names == deployment_env.keys() - {"PATH"}


def test_bundled_secondcontext_ownership_and_credentials(deployment_env):
    result = render(deployment_env, bundled=True)
    assert result.returncode == 0, "Synthetic bundled deployment configuration failed"
    config = json.loads(result.stdout)
    services = config["services"]
    assert set(services) == {
        "postgres",
        "redis",
        "astrology-mcp",
        "migrate",
        "gateway",
        "worker",
        "secondcontext",
        "secondcontext-migrate",
        "secondcontext-qdrant",
    }
    for name, service in services.items():
        assert "build" not in service and "env_file" not in service
        assert "ports" not in service or name == "gateway"
        assert "OPENAI_API_KEY" not in service.get("environment", {}) or name == "secondcontext"
    context = services["secondcontext"]
    migration = services["secondcontext-migrate"]
    assert context["image"] == migration["image"] == deployment_env["SECOND_CONTEXT_IMAGE"]
    assert context["read_only"] and migration["read_only"]
    assert context["user"] == migration["user"] == "65532:65532"
    assert migration["command"] == ["/app/migrate", "up"]
    assert set(migration["environment"]) == {
        "POSTGRES_ENABLED",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_SSLMODE",
    }
    assert context["environment"]["POSTGRES_HOST"] == "postgres"
    assert context["environment"]["POSTGRES_PASSWORD"] != deployment_env["POSTGRES_PASSWORD"]
    assert context["environment"]["AUTH_ENABLED"] == "true"
    assert context["environment"]["AUTH_SERVICE_TOKENS"] == (
        "oria:=" + deployment_env["SECOND_CONTEXT_BEARER_TOKEN"]
    )
    assert context["environment"]["KNOWLEDGE_ENABLED"] == "false"
    assert context["depends_on"]["secondcontext-migrate"]["condition"] == (
        "service_completed_successfully"
    )
    for name in ("gateway", "worker"):
        assert (
            services[name]["environment"]["SECOND_CONTEXT_BASE_URL"] == "http://secondcontext:8080"
        )
        assert services[name]["depends_on"]["secondcontext"]["condition"] == "service_healthy"
        assert "secondcontext-storage" not in services[name]["networks"]
    assert "secondcontext-api" in services["worker"]["networks"]
    assert set(migration["networks"]) == {"secondcontext-storage"}
    assert set(services["secondcontext-qdrant"]["networks"]) == {"secondcontext-storage"}
    assert set(services["postgres"]["networks"]) == {"storage", "secondcontext-storage"}
    assert services["postgres"]["environment"]["POSTGRES_USER"] == "postgres"
    assert (
        services["postgres"]["environment"]["POSTGRES_PASSWORD"]
        == deployment_env["POSTGRES_ADMIN_PASSWORD"]
    )
    assert len([s for s in services.values() if s["image"].startswith("postgres:")]) == 1
    for name in ("gateway", "worker", "migrate", "secondcontext", "secondcontext-migrate"):
        assert "POSTGRES_ADMIN_PASSWORD" not in services[name].get("environment", {})
        assert deployment_env["POSTGRES_ADMIN_PASSWORD"] not in str(services[name])
    assert config["networks"]["secondcontext-storage"]["internal"]
    assert config["networks"]["secondcontext-api"]["internal"]
    assert set(config["volumes"]) == {
        "shared_postgres_data",
        "secondcontext_qdrant_data",
    }
    assert not {"TELEGRAM_BOT_TOKEN", "PROFILE_ENCRYPTION_KEY", "QUAY_AUTH"} & (
        context["environment"].keys()
    )


@pytest.mark.parametrize(
    "missing",
    [
        "POSTGRES_ADMIN_PASSWORD",
        "SECOND_CONTEXT_IMAGE",
        "SECOND_CONTEXT_POSTGRES_PASSWORD",
        "SECOND_CONTEXT_OPENAI_API_KEY",
    ],
)
def test_missing_bundled_configuration_fails_closed(deployment_env, missing):
    deployment_env.pop(missing)
    result = render(deployment_env, bundled=True)
    assert result.returncode != 0
    assert not result.stdout
    assert missing in result.stderr
    assert deployment_env["SECOND_CONTEXT_BEARER_TOKEN"] not in result.stderr


def test_external_mode_needs_no_bundled_credentials(deployment_env):
    for name in (
        "POSTGRES_ADMIN_PASSWORD",
        "SECOND_CONTEXT_IMAGE",
        "SECOND_CONTEXT_POSTGRES_PASSWORD",
        "SECOND_CONTEXT_OPENAI_API_KEY",
    ):
        deployment_env.pop(name)
    result = render(deployment_env)
    assert result.returncode == 0, "External SecondContext configuration failed"
    config = json.loads(result.stdout)
    assert "secondcontext" not in config["services"]
    assert (
        config["services"]["worker"]["environment"]["SECOND_CONTEXT_BASE_URL"]
        == (deployment_env["SECOND_CONTEXT_BASE_URL"])
    )


def test_shared_postgres_database_isolation_and_restart(deployment_env):
    # Exercise the production bootstrap with quoted passwords, not copied schemas.
    deployment_env["POSTGRES_PASSWORD"] += "'\\$"
    deployment_env["SECOND_CONTEXT_POSTGRES_PASSWORD"] += "'\\$"
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        "oria-shared-db-test-" + uuid4().hex[:12],
        "-f",
        str(ROOT / "deploy/compose.full.yaml"),
    ]

    def compose(*args):
        result = subprocess.run(
            [*command, *args], env=deployment_env, capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, "Isolated shared PostgreSQL command failed"
        return result.stdout

    def query(role, database, sql, *, allowed=True, password_override=None):
        password = deployment_env[
            "POSTGRES_PASSWORD" if role == "oria" else "SECOND_CONTEXT_POSTGRES_PASSWORD"
        ]
        result = subprocess.run(
            [
                *command,
                "exec",
                "-T",
                "-e",
                "PGPASSWORD=" + (password_override or password),
                "postgres",
                "psql",
                "-h",
                "postgres",
                "-U",
                role,
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-Atc",
                sql,
            ],
            env=deployment_env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert (result.returncode == 0) == allowed, "Database ownership boundary failed"
        return result.stdout.strip()

    try:
        compose("up", "-d", "--wait", "--wait-timeout", "90", "postgres")
        for role in ("oria", "secondcontext"):
            assert (
                query(
                    role,
                    role,
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user",
                )
                == "f|f|f|f|f"
            )
            query(
                role,
                role,
                "CREATE TABLE bootstrap_probe (id integer); INSERT INTO bootstrap_probe VALUES (1)",
            )
            other = "secondcontext" if role == "oria" else "oria"
            query(role, other, "SELECT 1", allowed=False)
            query(role, role, "SET ROLE " + other, allowed=False)
        query("oria", "oria", "SELECT 1", allowed=False, password_override=secrets.token_hex(24))
        compose("down")
        compose("up", "-d", "--wait", "--wait-timeout", "90", "postgres")
        for role in ("oria", "secondcontext"):
            assert query(role, role, "SELECT id FROM bootstrap_probe") == "1"
    finally:
        compose("down", "--volumes", "--remove-orphans")
