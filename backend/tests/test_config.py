from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_unknown_dotenv_key_is_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BILI_AI_ENVIRONMNET=production\n", encoding="utf-8")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=env_file)

    [detail] = error.value.errors()
    assert detail["type"] == "extra_forbidden"
    assert detail["loc"] == ("bili_ai_environmnet",)
