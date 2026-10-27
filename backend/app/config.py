"""Runtime configuration, read from environment variables prefixed ``OPSCORE_``.

Production refuses to start with development defaults: a weak signing secret,
SQLite, or a notification provider that is selected but not configured. Every
environment refuses the public development secret on a non-SQLite database,
and the Claude answerer switched on without an API key.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPSCORE_", env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # OPSCORE_DATABASE_URL, or DATABASE_URL as set by Vercel's Neon (Postgres) integration.
    database_url: str = Field(
        default="sqlite:///./opscore.db", validation_alias=AliasChoices("OPSCORE_DATABASE_URL", "DATABASE_URL")
    )
    # Migrations need a role that owns the tables; the API should not. Defaults to database_url.
    # Neon's direct (unpooled) connection is preferred for migrations.
    migration_database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPSCORE_MIGRATION_DATABASE_URL", "DATABASE_URL_UNPOOLED"),
    )
    cors_origins: list[str] = Field(default_factory=list)

    # Authentication
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    access_token_ttl_minutes: int = Field(default=60, ge=5, le=24 * 60)
    login_attempts_per_minute: int = Field(default=10, ge=1)
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    # Event ingestion guards
    event_max_future_skew_seconds: int = Field(default=300, ge=0)
    event_max_age_days: int = Field(default=30, ge=1)
    inbound_requests_per_minute: int = Field(default=600, ge=1)

    # Bulk import guards
    import_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    import_max_rows: int = Field(default=20_000, ge=1)

    # Notifications
    notify_inline: bool = True
    # 30 s doubling to 1 h: ten attempts keep trying for about three hours.
    notification_max_attempts: int = Field(default=10, ge=1, le=20)
    email_provider: Literal["log", "smtp"] = "log"
    sms_provider: Literal["log", "twilio"] = "log"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_sms_from: str | None = None
    twilio_whatsapp_from: str | None = None

    # Ops Assistant
    assistant_llm_enabled: bool = False
    assistant_model: str = "claude-opus-5-5"
    assistant_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    assistant_idle_close_hours: int = Field(default=24, ge=1)
    assistant_history_messages: int = Field(default=10, ge=0, le=50)
    # Hand an escalated conversation back to the assistant when nobody has replied for this long.
    assistant_escalation_handback_hours: float = Field(default=8, gt=0, le=24 * 7)
    # OPSCORE_ANTHROPIC_API_KEY, or the SDK's own ANTHROPIC_API_KEY.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPSCORE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _postgres_driver(cls, value: str | None) -> str | None:
        """Hosted Postgres hands out postgres:// URLs; SQLAlchemy needs the psycopg driver named."""
        if value and value.startswith(("postgres://", "postgresql://")):
            return "postgresql+psycopg://" + value.split("://", 1)[1]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _refuse_unsafe_anywhere(self) -> "Settings":
        """Mistakes that are unsafe in every environment (production has its own, stricter list)."""
        if self.is_production:
            return self
        problems: list[str] = []
        if not self.database_url.startswith("sqlite") and self.jwt_secret.get_secret_value() == DEV_JWT_SECRET:
            problems.append(
                "OPSCORE_JWT_SECRET is the public development secret; set a random value of 32+ characters "
                "before using a shared database"
            )
        if self.assistant_llm_enabled and not (self.anthropic_api_key and self.anthropic_api_key.get_secret_value()):
            problems.append("OPSCORE_ASSISTANT_LLM_ENABLED=true needs OPSCORE_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY)")
        if problems:
            raise ValueError("Unsafe configuration: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> "Settings":
        if not self.is_production:
            return self
        problems: list[str] = []
        secret = self.jwt_secret.get_secret_value()
        if secret == DEV_JWT_SECRET or len(secret) < 32:
            problems.append("OPSCORE_JWT_SECRET must be set to a random value of 32+ characters")
        if self.bcrypt_rounds < 12:
            problems.append("OPSCORE_BCRYPT_ROUNDS must be at least 12 in production")
        if self.database_url.startswith("sqlite"):
            problems.append("OPSCORE_DATABASE_URL must point at PostgreSQL in production")
        if self.email_provider == "smtp" and not (self.smtp_host and self.smtp_from):
            problems.append("SMTP email needs OPSCORE_SMTP_HOST and OPSCORE_SMTP_FROM")
        if self.sms_provider == "twilio" and not (self.twilio_account_sid and self.twilio_auth_token):
            problems.append("Twilio needs OPSCORE_TWILIO_ACCOUNT_SID and OPSCORE_TWILIO_AUTH_TOKEN")
        if self.assistant_llm_enabled and not (self.anthropic_api_key and self.anthropic_api_key.get_secret_value()):
            problems.append("OPSCORE_ASSISTANT_LLM_ENABLED=true needs OPSCORE_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY)")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
