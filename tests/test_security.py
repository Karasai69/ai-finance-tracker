from app.security import create_token, hash_password, read_token, verify_password


def test_password_hash_and_verify():
    stored = hash_password("секрет123")
    assert stored.startswith("scrypt$")
    assert "секрет123" not in stored
    assert verify_password("секрет123", stored)
    assert not verify_password("неверный", stored)


def test_same_password_gives_different_hashes():
    assert hash_password("password123") != hash_password("password123")


def test_broken_hash_is_rejected():
    assert not verify_password("x", "garbage")
    assert not verify_password("x", "md5$a$b")


def test_token_roundtrip():
    assert read_token(create_token(42)) == 42


def test_expired_and_forged_tokens():
    assert read_token(create_token(42, days=-1)) is None
    assert read_token("not-a-token") is None
    token = create_token(42)
    assert read_token(token[:-2] + ("aa" if not token.endswith("aa") else "bb")) is None
