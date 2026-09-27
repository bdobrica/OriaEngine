from types import SimpleNamespace
from unittest.mock import patch

import pytest

from oria_engine.config import ConfigurationError, Settings
from oria_engine.db.local import require_local
from oria_engine.db.session import Database


async def test_database_creation_is_lazy_and_private():
    db = Database(Settings())
    try:
        assert db.engine.echo is False
        assert db.engine.sync_engine.hide_parameters is True
        assert db.sessions.kw["expire_on_commit"] is False
    finally:
        await db.close()


@pytest.mark.parametrize("environment", ["development", "test"])
def test_local_commands_allowed(environment):
    with patch(
        "oria_engine.db.local.load_settings", return_value=SimpleNamespace(app_env=environment)
    ):
        require_local()


def test_local_commands_reject_production():
    with (
        patch(
            "oria_engine.db.local.load_settings", return_value=SimpleNamespace(app_env="production")
        ),
        pytest.raises(ConfigurationError, match="development/test"),
    ):
        require_local()
