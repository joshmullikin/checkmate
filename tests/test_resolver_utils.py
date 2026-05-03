import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.utils.resolver import mask_passwords_in_steps, resolve_references


def test_mask_passwords_in_steps_masks_fill_form_and_type_actions():
    steps = [
        {
            "action": "fill_form",
            "value": json.dumps(
                {
                    "username": "alice",
                    "password": "plain-text",
                    "confirmPassword": "plain-text",
                }
            ),
        },
        {"action": "type", "target": "#password", "value": "plain-text"},
        {"action": "click", "target": "#submit", "value": "ignored"},
    ]

    masked = mask_passwords_in_steps(steps, mask="********")

    masked_form = json.loads(masked[0]["value"])
    assert masked_form["username"] == "alice"
    assert masked_form["password"] == "********"
    assert masked_form["confirmPassword"] == "********"
    assert masked[1]["value"] == "********"
    assert masked[2]["value"] == "ignored"


def test_mask_passwords_in_steps_handles_invalid_json_gracefully():
    steps = [{"action": "fill_form", "value": "{not-json"}]

    masked = mask_passwords_in_steps(steps)

    assert masked[0]["value"] == "{not-json"


def test_resolve_references_replaces_all_supported_patterns():
    session = MagicMock()
    project = SimpleNamespace(base_url="https://example.com/")
    pages = [SimpleNamespace(name="login", path="/login")]
    personas = [
        SimpleNamespace(
            name="alice",
            username="alice-user",
            encrypted_password="enc-pw",
            encrypted_api_key="enc-api",
            encrypted_token="enc-token",
            encrypted_metadata="enc-meta",
            environment_id=None,
        )
    ]
    test_data = [SimpleNamespace(name="seed", data='{"email":"a@example.com"}', environment_id=None)]

    decrypt_data_values = {
        "enc-api": "api-123",
        "enc-token": "token-xyz",
        "enc-meta": '{"role":"admin"}',
    }

    steps = [
        {"action": "navigate", "value": "{{login}}"},
        {"action": "navigate", "value": "/dashboard"},
        {"action": "type", "value": "{{alice.username}}"},
        {"action": "type", "value": "{{alice.password}}"},
        {"action": "type", "value": "{{alice.api_key}}"},
        {"action": "type", "value": "{{alice.token}}"},
        {"action": "type", "value": "{{alice.role}}"},
        {"action": "type", "value": "{{env.REGION}}"},
        {"action": "type", "value": "{{data.seed.email}}"},
        {"action": "type", "value": "{{unknown.value}}"},
    ]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), patch(
        "agent.utils.resolver.crud.get_pages_by_project", return_value=pages
    ), patch("agent.utils.resolver.crud.get_personas_by_project", return_value=personas), patch(
        "agent.utils.resolver.crud.get_test_data_by_project", return_value=test_data
    ), patch("agent.utils.resolver.decrypt_password", return_value="pw-plain"), patch(
        "agent.utils.resolver.decrypt_data",
        side_effect=lambda value: decrypt_data_values[value],
    ):
        resolved = resolve_references(
            session=session,
            project_id=1,
            steps=steps,
            env_vars={"REGION": "us-east-1"},
        )

    assert resolved[0]["value"] == "https://example.com/login"
    assert resolved[1]["value"] == "https://example.com/dashboard"
    assert resolved[2]["value"] == "alice-user"
    assert resolved[3]["value"] == "pw-plain"
    assert resolved[4]["value"] == "api-123"
    assert resolved[5]["value"] == "token-xyz"
    assert resolved[6]["value"] == "admin"
    assert resolved[7]["value"] == "us-east-1"
    assert resolved[8]["value"] == "a@example.com"
    assert resolved[9]["value"] == "{{unknown.value}}"


def test_resolve_references_environment_specific_items_override_globals():
    session = MagicMock()
    project = SimpleNamespace(base_url="https://example.com")
    pages = [SimpleNamespace(name="home", path="/home")]

    global_persona = SimpleNamespace(
        name="alice",
        username="global-user",
        encrypted_password=None,
        encrypted_api_key=None,
        encrypted_token=None,
        encrypted_metadata=None,
        environment_id=None,
    )
    env_persona = SimpleNamespace(
        name="alice",
        username="env-user",
        encrypted_password=None,
        encrypted_api_key=None,
        encrypted_token=None,
        encrypted_metadata=None,
        environment_id=2,
    )

    global_data = SimpleNamespace(name="seed", data='{"email":"global@example.com"}', environment_id=None)
    env_data = SimpleNamespace(name="seed", data='{"email":"env@example.com"}', environment_id=2)

    steps = [
        {"action": "type", "value": "{{alice.username}}"},
        {"action": "type", "value": "{{data.seed.email}}"},
    ]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), patch(
        "agent.utils.resolver.crud.get_pages_by_project", return_value=pages
    ), patch(
        "agent.utils.resolver.crud.get_personas_by_project",
        return_value=[global_persona, env_persona],
    ), patch(
        "agent.utils.resolver.crud.get_test_data_by_project",
        return_value=[global_data, env_data],
    ):
        resolved = resolve_references(
            session=session,
            project_id=1,
            steps=steps,
            environment_id=2,
        )

    assert resolved[0]["value"] == "env-user"
    assert resolved[1]["value"] == "env@example.com"


def test_resolve_references_decrypt_password_exception_returns_placeholder():
    """Test that decrypt exception for password returns original placeholder."""
    from unittest.mock import patch, MagicMock
    from types import SimpleNamespace
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    persona = SimpleNamespace(
        name="bob",
        username="bob",
        encrypted_password="bad-enc",
        encrypted_api_key=None,
        encrypted_token=None,
        encrypted_metadata=None,
        environment_id=None,
    )
    steps = [{"action": "type", "value": "{{bob.password}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[persona]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]), \
         patch("agent.utils.resolver.decrypt_password", side_effect=Exception("key error")):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    # Should return the original placeholder when decryption fails
    assert resolved[0]["value"] == "{{bob.password}}"


def test_resolve_references_decrypt_api_key_exception_returns_placeholder():
    """Test that decrypt exception for api_key returns original placeholder."""
    from unittest.mock import patch, MagicMock
    from types import SimpleNamespace
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    persona = SimpleNamespace(
        name="bob",
        username="bob",
        encrypted_password=None,
        encrypted_api_key="bad-enc",
        encrypted_token=None,
        encrypted_metadata=None,
        environment_id=None,
    )
    steps = [{"action": "type", "value": "{{bob.api_key}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[persona]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]), \
         patch("agent.utils.resolver.decrypt_data", side_effect=Exception("key error")):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == "{{bob.api_key}}"


def test_resolve_references_decrypt_token_exception_returns_placeholder():
    """Test that decrypt exception for token returns original placeholder."""
    from unittest.mock import patch, MagicMock
    from types import SimpleNamespace
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    persona = SimpleNamespace(
        name="bob",
        username="bob",
        encrypted_password=None,
        encrypted_api_key=None,
        encrypted_token="bad-enc",
        encrypted_metadata=None,
        environment_id=None,
    )
    steps = [{"action": "type", "value": "{{bob.token}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[persona]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]), \
         patch("agent.utils.resolver.decrypt_data", side_effect=Exception("key error")):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == "{{bob.token}}"


def test_resolve_references_decrypt_metadata_exception_returns_placeholder():
    """Test that decrypt exception for custom field returns original placeholder."""
    from unittest.mock import patch, MagicMock
    from types import SimpleNamespace
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    persona = SimpleNamespace(
        name="bob",
        username="bob",
        encrypted_password=None,
        encrypted_api_key=None,
        encrypted_token=None,
        encrypted_metadata="bad-enc",
        environment_id=None,
    )
    steps = [{"action": "type", "value": "{{bob.custom_field}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[persona]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]), \
         patch("agent.utils.resolver.decrypt_data", side_effect=Exception("key error")):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == "{{bob.custom_field}}"


def test_resolve_references_data_json_decode_error_returns_placeholder():
    """Test that JSONDecodeError in test data returns original placeholder."""
    from unittest.mock import patch, MagicMock
    from types import SimpleNamespace
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    test_data = [SimpleNamespace(name="ds", data="not-json", environment_id=None)]
    steps = [{"action": "type", "value": "{{data.ds.field}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=test_data):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == "{{data.ds.field}}"


def test_resolve_references_no_project_base_url_uses_empty():
    """Test resolve_references when project has no base_url."""
    from unittest.mock import patch, MagicMock
    from types import SimpleNamespace
    session = MagicMock()

    with patch("agent.utils.resolver.crud.get_project", return_value=None), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]):
        resolved = resolve_references(session=session, project_id=1, steps=[
            {"action": "navigate", "value": "/home"}
        ])
    # Without base_url, relative URL stays as-is
    assert resolved[0]["value"] == "/home"


def test_mask_passwords_in_steps_non_string_value_is_passthrough():
    """Branch 33->50: non-string value is not modified."""
    steps = [{"action": "click", "value": 42}]
    masked = mask_passwords_in_steps(steps)
    assert masked[0]["value"] == 42


def test_mask_passwords_in_steps_type_without_password_in_target():
    """Branch 48->50: type action with non-password target is unchanged."""
    steps = [{"action": "type", "target": "#username", "value": "alice"}]
    masked = mask_passwords_in_steps(steps)
    assert masked[0]["value"] == "alice"


def test_resolve_references_unknown_page_returns_placeholder():
    """Branch 168: {{unknown_page}} returns original placeholder."""
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    steps = [{"action": "type", "value": "{{missing_page}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == "{{missing_page}}"


def test_resolve_references_data_unknown_prefix_returns_placeholder():
    """Branch 112->119: 3-part ref with wrong prefix returns placeholder."""
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    td = SimpleNamespace(name="seed", data='{"key":"val"}', environment_id=None)
    steps = [{"action": "type", "value": "{{other.seed.key}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[td]):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == "{{other.seed.key}}"


def test_resolve_references_data_field_not_in_parsed_returns_placeholder():
    """Branch 115->119: data field not in parsed dict returns placeholder."""
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    td = SimpleNamespace(name="seed", data='{"key":"val"}', environment_id=None)
    steps = [{"action": "type", "value": "{{data.seed.missing_field}}"}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[td]):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == "{{data.seed.missing_field}}"


def _make_persona(name="bob", **overrides):
    defaults = dict(
        name=name, username="bob",
        encrypted_password=None, encrypted_api_key=None,
        encrypted_token=None, encrypted_metadata=None,
        environment_id=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _resolve_one(steps, persona):
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[persona]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]):
        return resolve_references(session=session, project_id=1, steps=steps)


def test_resolve_references_password_no_encrypted_value_returns_placeholder():
    """Branch 134->138: encrypted_password is None returns placeholder."""
    persona = _make_persona(encrypted_password=None)
    resolved = _resolve_one([{"action": "type", "value": "{{bob.password}}"}], persona)
    assert resolved[0]["value"] == "{{bob.password}}"


def test_resolve_references_api_key_no_encrypted_value_returns_placeholder():
    """Branch 141->145: encrypted_api_key is None returns placeholder."""
    persona = _make_persona(encrypted_api_key=None)
    resolved = _resolve_one([{"action": "type", "value": "{{bob.api_key}}"}], persona)
    assert resolved[0]["value"] == "{{bob.api_key}}"


def test_resolve_references_token_no_encrypted_value_returns_placeholder():
    """Branch 148->152: encrypted_token is None returns placeholder."""
    persona = _make_persona(encrypted_token=None)
    resolved = _resolve_one([{"action": "type", "value": "{{bob.token}}"}], persona)
    assert resolved[0]["value"] == "{{bob.token}}"


def test_resolve_references_metadata_no_encrypted_value_returns_placeholder():
    """Branch 156->162: encrypted_metadata is None returns placeholder."""
    persona = _make_persona(encrypted_metadata=None)
    resolved = _resolve_one([{"action": "type", "value": "{{bob.custom_field}}"}], persona)
    assert resolved[0]["value"] == "{{bob.custom_field}}"


def test_resolve_references_metadata_field_not_in_dict_returns_placeholder():
    """Branch 158->162: metadata dict does not contain the field."""
    persona = _make_persona(encrypted_metadata="enc-meta")
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[persona]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]), \
         patch("agent.utils.resolver.decrypt_data", return_value='{"other":"val"}'):
        resolved = resolve_references(session=session, project_id=1, steps=[
            {"action": "type", "value": "{{bob.missing_field}}"}
        ])
    assert resolved[0]["value"] == "{{bob.missing_field}}"


def test_resolve_references_non_string_step_value_passthrough():
    """Branch 174: resolve_value returns non-string values unchanged."""
    session = MagicMock()
    project = SimpleNamespace(base_url="")
    steps = [{"action": "click", "value": 99}]

    with patch("agent.utils.resolver.crud.get_project", return_value=project), \
         patch("agent.utils.resolver.crud.get_pages_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_personas_by_project", return_value=[]), \
         patch("agent.utils.resolver.crud.get_test_data_by_project", return_value=[]):
        resolved = resolve_references(session=session, project_id=1, steps=steps)
    assert resolved[0]["value"] == 99
