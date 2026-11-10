from publish.settings import SettingsHolder, load_settings_schema


def test_defaults_from_schema():
    schema = load_settings_schema()
    assert schema["properties"]["dry_run"]["default"] is True
    h = SettingsHolder()
    s = h.get()
    assert s.dry_run is True
    assert s.instagram.get("client") == "fake"
