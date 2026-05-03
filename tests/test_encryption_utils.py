import pytest
from cryptography.fernet import Fernet

import db.encryption as encryption


@pytest.fixture(autouse=True)
def reset_fernet_cache():
    original_key = encryption.ENCRYPTION_KEY
    original_fernet = encryption._fernet
    encryption._fernet = None
    yield
    encryption.ENCRYPTION_KEY = original_key
    encryption._fernet = original_fernet


def test_get_fernet_raises_without_key():
    encryption.ENCRYPTION_KEY = None

    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        encryption._get_fernet()


def test_password_encryption_round_trip():
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()

    encrypted = encryption.encrypt_password("secret-pass")
    decrypted = encryption.decrypt_password(encrypted)

    assert encrypted != "secret-pass"
    assert decrypted == "secret-pass"


def test_data_encryption_round_trip():
    encryption.ENCRYPTION_KEY = Fernet.generate_key().decode()

    payload = '{"token":"abc123"}'
    encrypted = encryption.encrypt_data(payload)
    decrypted = encryption.decrypt_data(encrypted)

    assert encrypted != payload
    assert decrypted == payload