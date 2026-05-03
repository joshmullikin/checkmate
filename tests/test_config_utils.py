import core.config as config


def test_env_bool_truthy_values(monkeypatch):
    monkeypatch.setenv("FEATURE_FLAG", "true")
    assert config._env_bool("FEATURE_FLAG") is True

    monkeypatch.setenv("FEATURE_FLAG", "1")
    assert config._env_bool("FEATURE_FLAG") is True

    monkeypatch.setenv("FEATURE_FLAG", "yes")
    assert config._env_bool("FEATURE_FLAG") is True


def test_env_bool_defaults_and_falsy(monkeypatch):
    monkeypatch.delenv("FEATURE_FLAG", raising=False)
    assert config._env_bool("FEATURE_FLAG", default=False) is False
    assert config._env_bool("FEATURE_FLAG", default=True) is True

    monkeypatch.setenv("FEATURE_FLAG", "false")
    assert config._env_bool("FEATURE_FLAG", default=True) is False


def test_parse_remotes_handles_valid_and_invalid_entries():
    parsed = config._parse_remotes(
        "prod:https://api.example.com/, bad-entry, staging:https://staging.example.com"
    )

    assert parsed == [
        {"name": "prod", "url": "https://api.example.com"},
        {"name": "staging", "url": "https://staging.example.com"},
    ]


def test_parse_remotes_empty_input():
    assert config._parse_remotes("") == []
    assert config._parse_remotes("   ") == []