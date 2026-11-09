from __future__ import annotations

from review.settings import SettingsHolder, load_settings_schema


def test_defaults_load_from_schema() -> None:
    holder = SettingsHolder()
    s = holder.get()
    assert s.timezone == "UTC"
    assert s.telegram.get("bot_credential") == "cred:telegram-review-bot"
    assert holder.source == "defaults"


def test_schema_id() -> None:
    schema = load_settings_schema()
    assert schema["$id"].endswith("/settings/1")
    assert schema["additionalProperties"] is False
