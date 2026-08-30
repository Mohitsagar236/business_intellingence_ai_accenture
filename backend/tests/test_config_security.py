"""
JWT secret hardening (final hardening pass, item 1). Settings() is constructed directly with
explicit kwargs in every test here — pydantic-settings gives constructor kwargs the highest
precedence (above real environment variables and the developer's own .env file), so these
never depend on what's actually sitting in backend/.env on whatever machine runs them.
"""
from __future__ import annotations

import pytest

from app.config import INSECURE_DEFAULT_JWT_SECRET, MIN_PRODUCTION_JWT_SECRET_LENGTH, Settings


def test_development_with_the_default_secret_is_allowed():
    settings = Settings(app_env="development", jwt_secret=INSECURE_DEFAULT_JWT_SECRET)
    assert settings.jwt_secret == INSECURE_DEFAULT_JWT_SECRET


def test_production_with_a_secure_secret_is_allowed():
    secret = "a" * MIN_PRODUCTION_JWT_SECRET_LENGTH
    settings = Settings(app_env="production", jwt_secret=secret)
    assert settings.jwt_secret == secret


def test_production_with_the_insecure_default_is_rejected():
    with pytest.raises(Exception, match="insecure default"):
        Settings(app_env="production", jwt_secret=INSECURE_DEFAULT_JWT_SECRET)


def test_production_with_a_too_short_secret_is_rejected():
    with pytest.raises(Exception, match="at least"):
        Settings(app_env="production", jwt_secret="short-secret")


def test_app_env_comparison_is_case_insensitive():
    with pytest.raises(Exception):
        Settings(app_env="Production", jwt_secret=INSECURE_DEFAULT_JWT_SECRET)


def test_rejection_error_never_includes_the_actual_secret_value():
    secret = "short-but-unique-marker-value"
    try:
        Settings(app_env="production", jwt_secret=secret)
        pytest.fail("expected Settings construction to raise")
    except Exception as exc:
        assert secret not in str(exc)
