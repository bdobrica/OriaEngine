import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oria_engine.__main__ import main as gateway_main
from oria_engine.config import Settings
from oria_engine.container_health import main, worker_ready
from oria_engine.queue.__main__ import run as run_worker


@pytest.mark.parametrize("argv,host", [([], "127.0.0.1"), (["--host", "0.0.0.0"], "0.0.0.0")])
def test_gateway_launcher_preserves_private_logging(argv, host):
    with patch("oria_engine.__main__.create_app"), patch("oria_engine.__main__.uvicorn.run") as run:
        gateway_main(argv)
    assert run.call_args.kwargs == {
        "host": host,
        "port": 8001,
        "log_config": None,
        "access_log": False,
    }


@pytest.mark.parametrize("age", [91, -10])
async def test_stale_or_future_worker_marker_is_unhealthy(tmp_path, age):
    marker = tmp_path / "health"
    marker.touch()
    os.utime(marker, (time.time() - age, time.time() - age))
    with patch("oria_engine.container_health.Database") as database:
        assert not await worker_ready(marker)
    database.assert_not_called()


@pytest.mark.parametrize("redis_ready", [True, False])
async def test_worker_probe_checks_storage_and_cleans_up(tmp_path, redis_ready):
    marker = tmp_path / "health"
    marker.touch()
    database = MagicMock()
    database.close = AsyncMock()
    connection = AsyncMock()
    database.engine.connect.return_value.__aenter__.return_value = connection
    redis = AsyncMock()
    redis.ping.return_value = redis_ready
    with (
        patch("oria_engine.container_health.Database", return_value=database),
        patch("oria_engine.container_health.Redis.from_url", return_value=redis),
    ):
        assert await worker_ready(marker) is redis_ready
    connection.execute.assert_awaited_once()
    redis.ping.assert_awaited_once()
    database.close.assert_awaited_once()
    redis.aclose.assert_awaited_once()


@pytest.mark.parametrize("role", ["gateway", "worker"])
def test_failed_probes_emit_no_sensitive_diagnostics(role, capsys):
    with (
        patch(
            "oria_engine.container_health.urllib.request.build_opener",
            side_effect=RuntimeError("private"),
        ),
        patch("oria_engine.container_health.worker_ready", side_effect=RuntimeError("private")),
        pytest.raises(SystemExit) as result,
    ):
        main([role])
    assert result.value.code == 1
    assert capsys.readouterr() == ("", "")


def test_worker_marker_tracks_recovery_loop_and_is_removed_on_shutdown(tmp_path):
    marker = tmp_path / "health"
    marker.touch()
    stop = MagicMock()
    stop.is_set.side_effect = [False, True]
    stop.wait.side_effect = lambda timeout: marker.exists() or pytest.fail("Missing heartbeat")
    worker = MagicMock()
    worker.start.side_effect = lambda: not marker.exists() or pytest.fail("Stale heartbeat")
    publisher = MagicMock()
    with (
        patch("oria_engine.queue.__main__.ProfileEncryption"),
        patch("oria_engine.queue.__main__.LocalPlaceResolver"),
        patch("oria_engine.queue.__main__.Publisher", return_value=publisher),
        patch("oria_engine.queue.__main__.Event", return_value=stop),
        patch("oria_engine.queue.__main__.signal.signal"),
        patch("oria_engine.queue.__main__.dramatiq.actor", return_value=lambda function: function),
        patch("oria_engine.queue.__main__.Worker", return_value=worker),
        patch("oria_engine.queue.__main__.recover", new_callable=AsyncMock) as recover,
    ):
        run_worker(
            Settings(_env_file=None, telegram_bot_token="123456:synthetic"), health_file=marker
        )
    recover.assert_awaited_once()
    stop.wait.assert_called_once_with(5)
    worker.stop.assert_called_once_with(timeout=70000)
    publisher.close.assert_called_once()
    assert not marker.exists()
