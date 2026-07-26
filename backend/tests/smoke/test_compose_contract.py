from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
CADDYFILE = ROOT / "deploy" / "Caddyfile"
ENV_EXAMPLE = ROOT / "deploy" / ".env.example"


def test_compose_contract_defines_roles_health_and_ephemeral_media() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["api"]["command"] == ["python", "-m", "app", "api"]
    assert services["dispatcher"]["command"] == ["python", "-m", "app", "dispatcher"]
    assert services["worker"]["command"] == ["python", "-m", "app", "worker"]
    for role in ("api", "dispatcher", "worker"):
        assert services[role]["depends_on"]["migrate"]["condition"] == (
            "service_completed_successfully"
        )

    assert "postgres_data" in compose["volumes"]
    assert any(
        volume.endswith("postgres_data:/var/lib/postgresql/data")
        or volume.endswith("/var/lib/postgresql/data")
        for volume in services["postgres"]["volumes"]
    )
    assert services["postgres"]["ports"] == [
        "127.0.0.1:${POSTGRES_HOST_PORT:-5432}:5432"
    ]
    assert "volumes" not in services["redis"]
    assert any(item.startswith("/tmp/bili-ai-media") for item in services["worker"]["tmpfs"])

    assert "healthcheck" in services["postgres"]
    assert "healthcheck" in services["redis"]
    assert "healthcheck" in services["api"]
    assert "/ready" in services["api"]["healthcheck"]["test"][-1]
    assert services["caddy"]["ports"] == ["${TLS_PORT:-443}:443"]
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in services["caddy"]["volumes"]
    assert services["caddy"]["environment"]["CADDY_SITE_ADDRESS"] == (
        "${CADDY_SITE_ADDRESS:-https://localhost}"
    )
    assert "BILI_AI_BCUT_API_BASE" in services["worker"]["environment"]
    assert "BILI_AI_MEDIA_WORKSPACE_MAX_BYTES" in services["worker"]["environment"]
    assert "BILI_AI_MEDIA_COMMAND_TIMEOUT_SECONDS" in services["worker"]["environment"]
    assert "BILI_AI_ANALYSIS_TASK_TIMEOUT_SECONDS" in services["worker"]["environment"]
    assert services["extension-build"]["volumes"] == ["../extension/dist:/out"]
    assert services["worker"]["deploy"]["replicas"] == "${WORKER_REPLICAS:-2}"
    for service in ("postgres", "redis", "migrate", "api", "dispatcher", "worker", "caddy"):
        limits = services[service]["deploy"]["resources"]["limits"]
        assert "cpus" in limits
        assert "memory" in limits

    extension_dockerfile = (ROOT / "deploy" / "extension.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "FROM scratch" not in extension_dockerfile
    assert 'cp -R /dist/. /out/' in extension_dockerfile

    caddy_text = CADDYFILE.read_text(encoding="utf-8")
    assert caddy_text.startswith("{$CADDY_SITE_ADDRESS:https://localhost}")
    assert "tls /certs/site.pem /certs/site-key.pem" in caddy_text
    for path in ("/api/*", "/health", "/ready"):
        assert f"reverse_proxy {path} api:8000" in caddy_text

    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for forbidden in ("postgres:postgres", "password=postgres", "changeme", "secret"):
        assert forbidden not in env_text.lower()
    assert "POSTGRES_PASSWORD=" in env_text
    assert "BILI_AI_DATABASE_URL=" in env_text
    assert "BILI_AI_BCUT_API_BASE=" in env_text
    assert "PERF_QUERY_PER_MINUTE_LIMIT=1000000" in env_text
    assert "CADDY_SITE_ADDRESS=https://localhost" in env_text
    assert "WORKER_REPLICAS=2" in env_text
    assert "PERF_CA_CERT=" in env_text
