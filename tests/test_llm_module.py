import types
import sys

import pytest

import agent.llm as llm


def test_load_function_invalid_path_raises():
    with pytest.raises(ValueError):
        llm._load_function("invalid_path")


def test_load_function_returns_callable():
    module = types.ModuleType("tmp_llm_mod")

    def get_key():
        return "k"

    module.get_key = get_key
    sys.modules["tmp_llm_mod"] = module

    fn = llm._load_function("tmp_llm_mod.get_key")
    assert callable(fn)
    assert fn() == "k"


def test_get_api_key_prefers_static_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "static-key")
    monkeypatch.setenv("LLM_API_KEY_FUNCTION", "tmp_llm_mod.get_key")
    assert llm._get_api_key("OPENAI_API_KEY", "LLM_API_KEY_FUNCTION") == "static-key"


def test_get_api_key_uses_function(monkeypatch):
    module = types.ModuleType("tmp_llm_key_mod")
    module.resolve_key = lambda: "function-key"
    sys.modules["tmp_llm_key_mod"] = module

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY_FUNCTION", "tmp_llm_key_mod.resolve_key")

    assert llm._get_api_key("OPENAI_API_KEY", "LLM_API_KEY_FUNCTION") == "function-key"


def test_get_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY_FUNCTION", raising=False)
    with pytest.raises(ValueError):
        llm._get_api_key("OPENAI_API_KEY", "LLM_API_KEY_FUNCTION")


def test_get_http_clients_verify_disabled(monkeypatch):
    monkeypatch.setenv("LLM_SSL_VERIFY", "false")
    client, async_client = llm._get_http_clients()
    assert client is not None
    assert async_client is not None
    client.close()
    import asyncio
    asyncio.run(async_client.aclose())


def test_get_http_clients_verify_enabled_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_SSL_VERIFY", "true")
    client, async_client = llm._get_http_clients()
    assert client is None
    assert async_client is None


def test_validate_config_openai_missing_key_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY_FUNCTION", raising=False)
    with pytest.raises(ValueError):
        llm.validate_config()


def test_validate_config_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(ValueError):
        llm.validate_config()


def test_validate_config_azure_missing_fields_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY_FUNCTION", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_DEFAULT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_FAST", raising=False)
    with pytest.raises(ValueError):
        llm.validate_config()


def test_has_api_key_from_env_and_function(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert llm._has_api_key("OPENAI_API_KEY", "LLM_API_KEY_FUNCTION") is True

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    module = types.ModuleType("tmp_llm_key_mod2")
    module.resolve_key = lambda: "k2"
    sys.modules["tmp_llm_key_mod2"] = module
    monkeypatch.setenv("LLM_API_KEY_FUNCTION", "tmp_llm_key_mod2.resolve_key")
    assert llm._has_api_key("OPENAI_API_KEY", "LLM_API_KEY_FUNCTION") is True


def test_has_api_key_invalid_function_returns_false(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY_FUNCTION", "nope.module.fn")
    assert llm._has_api_key("OPENAI_API_KEY", "LLM_API_KEY_FUNCTION") is False


def test_get_llm_openai_and_azure(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    called = {}

    def fake_openai(tier):
        called["openai"] = tier
        return {"provider": "openai", "tier": tier}

    def fake_azure(tier):
        called["azure"] = tier
        return {"provider": "azure", "tier": tier}

    monkeypatch.setattr(llm, "_get_openai_model", fake_openai)
    monkeypatch.setattr(llm, "_get_azure_model", fake_azure)

    got_openai = llm.get_llm("fast")
    assert got_openai == {"provider": "openai", "tier": "fast"}
    assert called["openai"] == "fast"

    monkeypatch.setenv("LLM_PROVIDER", "azure")
    got_azure = llm.get_llm("default")
    assert got_azure == {"provider": "azure", "tier": "default"}
    assert called["azure"] == "default"


def test_get_openai_model_passes_expected_kwargs(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("LLM_MODEL_FAST", "custom-fast")
    monkeypatch.setenv("LLM_SSL_VERIFY", "true")

    llm._get_openai_model("fast")
    assert captured["api_key"] == "openai-key"
    assert captured["model"] == "custom-fast"
    assert "http_client" not in captured


def test_get_azure_model_passes_expected_kwargs(monkeypatch):
    captured = {}

    class FakeAzureChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "AzureChatOpenAI", FakeAzureChatOpenAI)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_DEFAULT", "dep-default")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-01-01")

    llm._get_azure_model("default")
    assert captured["azure_deployment"] == "dep-default"
    assert captured["azure_endpoint"] == "https://example.azure.com"
    assert captured["api_key"] == "azure-key"
    assert captured["api_version"] == "2024-01-01"


def test_get_azure_model_missing_deployment_raises(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_DEFAULT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    with pytest.raises(ValueError):
        llm._get_azure_model("default")


def test_load_function_not_callable_raises_value_error():
    mod = types.ModuleType("tmp_llm_not_callable")
    mod.not_callable = "hello"
    sys.modules["tmp_llm_not_callable"] = mod

    with pytest.raises(ValueError, match="not callable"):
        llm._load_function("tmp_llm_not_callable.not_callable")


def test_get_llm_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "something-else")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        llm.get_llm("default")


def test_get_openai_model_includes_http_clients_when_ssl_disabled(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("LLM_SSL_VERIFY", "false")

    llm._get_openai_model("default")

    assert "http_client" in captured
    assert "http_async_client" in captured
    captured["http_client"].close()
    import asyncio
    asyncio.run(captured["http_async_client"].aclose())


def test_get_azure_model_missing_endpoint_raises(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_DEFAULT", "dep-default")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")

    with pytest.raises(ValueError, match="Azure endpoint not configured"):
        llm._get_azure_model("default")


def test_get_azure_model_includes_http_clients_when_ssl_disabled(monkeypatch):
    captured = {}

    class FakeAzureChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "AzureChatOpenAI", FakeAzureChatOpenAI)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_FAST", "dep-fast")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("LLM_SSL_VERIFY", "0")

    llm._get_azure_model("fast")

    assert captured["azure_deployment"] == "dep-fast"
    assert "http_client" in captured
    assert "http_async_client" in captured
    captured["http_client"].close()
    import asyncio
    asyncio.run(captured["http_async_client"].aclose())


def test_validate_config_azure_complete_passes(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_DEFAULT", "dep-default")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_FAST", "dep-fast")

    llm.validate_config()


def test_validate_config_openai_with_key_passes(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    llm.validate_config()