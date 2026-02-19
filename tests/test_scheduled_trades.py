from datetime import datetime
from pathlib import Path

import pytz

from config.settings import settings
import execution.scheduled_trades as scheduled_trades


def _configure_tmp_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings.schedule, "state_dir", tmp_path)
    monkeypatch.setattr(settings.schedule, "archive_dir", tmp_path / "archive")
    monkeypatch.setattr(settings.schedule, "scheduled_orders_file", "scheduled_orders.json")
    monkeypatch.setattr(settings.schedule, "scheduler_state_file", "scheduler_state.json")
    settings.schedule.state_dir.mkdir(parents=True, exist_ok=True)
    settings.schedule.archive_dir.mkdir(parents=True, exist_ok=True)


def test_save_and_load_scheduled_orders_roundtrip(monkeypatch, tmp_path):
    _configure_tmp_state(monkeypatch, tmp_path)

    orders = [{"symbol": "MU", "side": "buy", "quantity": 10.0}]
    path = scheduled_trades.save_scheduled_orders(
        orders,
        strategy_name="RAMmageddon",
        equity_snapshot=100000.0,
        signals_snapshot={"MU": 75.0},
    )

    assert path.exists()
    payload = scheduled_trades.load_scheduled_orders()
    assert payload is not None
    assert payload["strategy"] == "RAMmageddon"
    assert payload["equity_snapshot"] == 100000.0
    assert payload["signals_snapshot"]["MU"] == 75.0
    assert payload["orders"][0]["symbol"] == "MU"


def test_scheduler_state_roundtrip(monkeypatch, tmp_path):
    _configure_tmp_state(monkeypatch, tmp_path)

    state = {
        "last_after_hours_date": "2026-02-19",
        "last_execute_open_date": "2026-02-20",
    }
    scheduled_trades.write_scheduler_state(state)
    loaded = scheduled_trades.read_scheduler_state()
    assert loaded == state


def test_should_run_windows_and_once_per_day(monkeypatch, tmp_path):
    _configure_tmp_state(monkeypatch, tmp_path)
    tz = pytz.timezone(settings.schedule.timezone)

    # Ensure default schedule times used by tests
    monkeypatch.setattr(settings.schedule, "after_hours_hour", 16)
    monkeypatch.setattr(settings.schedule, "after_hours_minute", 35)
    monkeypatch.setattr(settings.schedule, "market_open_hour", 9)
    monkeypatch.setattr(settings.schedule, "market_open_minute", 31)

    after_hours_now = tz.localize(datetime(2026, 2, 20, 16, 40, 0))
    execute_now = tz.localize(datetime(2026, 2, 20, 9, 33, 0))

    # No state: should run inside windows
    assert scheduled_trades.should_run_after_hours(after_hours_now) is True
    assert scheduled_trades.should_run_execute_open(execute_now) is True

    # Mark as already run today: should not run again
    scheduled_trades.write_scheduler_state(
        {
            "last_after_hours_date": "2026-02-20",
            "last_execute_open_date": "2026-02-20",
        }
    )
    assert scheduled_trades.should_run_after_hours(after_hours_now) is False
    assert scheduled_trades.should_run_execute_open(execute_now) is False
