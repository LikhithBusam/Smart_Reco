import uuid

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_produces_different_hash_than_input():
    hashed = hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"


def test_verify_password_accepts_correct_password():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", hashed) is False


def test_access_token_round_trip_contains_subject_and_role():
    user_id = uuid.uuid4()
    token = create_access_token(user_id, "admin")

    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["role"] == "admin"


def test_decode_access_token_rejects_tampered_token():
    user_id = uuid.uuid4()
    token = create_access_token(user_id, "user")
    # Flip a char well inside the payload, not the last char of the signature —
    # base64's trailing padding bits are redundant and don't always change the
    # decoded bytes, which makes a last-char flip flaky.
    i = len(token) // 2
    tampered = token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1 :]

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered)
