from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_database_url_uses_prefixed_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = "postgresql+asyncpg://postgres@localhost:5432/bili_ai_test"
    monkeypatch.setenv("BILI_AI_DATABASE_URL", database_url)

    assert Settings(_env_file=None).database_url == database_url


def test_extension_origins_are_exact_and_token_entropy_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, token_byte_length=31)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allowed_extension_origins=["https://example.com"])
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            allowed_extension_origins=["chrome-extension://approved/path"],
        )


def test_unknown_dotenv_key_is_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BILI_AI_ENVIRONMNET=production\n", encoding="utf-8")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=env_file)

    [detail] = error.value.errors()
    assert detail["type"] == "extra_forbidden"
    assert detail["loc"] == ("bili_ai_environmnet",)
