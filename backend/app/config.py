"""Environment-based settings. Never hardcode secrets here."""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Published in this repo's own .env.example — anyone can read it, so it must never be usable
# once APP_ENV=production. Kept as a named constant (not inlined) so the comparison below and
# the tests that exercise it can't drift apart.
INSECURE_DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me"
MIN_PRODUCTION_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "development" (default) allows the published insecure JWT_SECRET default below so a
    # fresh checkout runs with zero config. Set APP_ENV=production to turn on the hard startup
    # check in _require_secure_jwt_secret_in_production — never silently trust this at that
    # point, since it's the difference between "convenient default" and "anyone can forge a
    # valid admin session".
    app_env: str = "development"

    database_url: str = "sqlite:///./data/app.db"
    # Three ways to reach an LLM for narrative generation. Priority: Gemini, then OpenRouter,
    # then direct Anthropic — Gemini first because it's the provider actually reachable with a
    # working (non-zero-balance) key in this deployment; the relative OpenRouter-before-Anthropic
    # order is unchanged from before. None set -> deterministic template fallback.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    openrouter_api_key: str | None = None
    openrouter_model: str = "anthropic/claude-sonnet-5"
    cors_origins: str = "http://localhost:5173"

    # Dev default only — override via env in any shared/deployed environment. Signs the login
    # JWTs; anyone with this value can mint a valid session for any role. See
    # _require_secure_jwt_secret_in_production — this default is refused outright once
    # APP_ENV=production rather than silently accepted.
    jwt_secret: str = INSECURE_DEFAULT_JWT_SECRET

    # DEBUG/INFO/WARNING/ERROR — see app/logging_config.py.
    log_level: str = "INFO"

    # Pipeline thresholds — kept here (not scattered in code) so they're one place to tune.
    significance_z_threshold: float = 2.0
    min_window_sample_size: int = 5
    correlation_threshold: float = 0.5
    theme_spike_ratio_threshold: float = 1.6
    max_lag_days: int = 3
    default_window_days: int = 10

    # Benjamini-Hochberg FDR level for the structured-correlation multiple-comparison
    # correction (evidence_mining.find_structured_correlate tests many metrics x lags per
    # search) — the conventional default for exploratory discovery, see the docstring there.
    fdr_alpha: float = 0.05

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _require_secure_jwt_secret_in_production(self) -> "Settings":
        """Fails fast at startup (Settings() is constructed once, eagerly, by get_settings())
        rather than letting a production deployment silently run signing tokens with a secret
        published in this repo's own .env.example. Never logs/prints self.jwt_secret — only
        its length and whether it matches the known default are ever mentioned."""
        if self.app_env.strip().lower() != "production":
            return self
        if self.jwt_secret == INSECURE_DEFAULT_JWT_SECRET:
            raise ValueError(
                "APP_ENV=production but JWT_SECRET is still the published insecure default from "
                ".env.example. Set a real random JWT_SECRET before starting in production, e.g.: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if len(self.jwt_secret) < MIN_PRODUCTION_JWT_SECRET_LENGTH:
            raise ValueError(
                f"APP_ENV=production requires JWT_SECRET to be at least {MIN_PRODUCTION_JWT_SECRET_LENGTH} "
                f"characters (got {len(self.jwt_secret)}). Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
