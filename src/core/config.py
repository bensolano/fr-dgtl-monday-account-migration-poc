from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration via environment variables.
    Local development overrides can be provided in a .env file.
    """

    PROJECT_ID: str = "sandbox-bsolano"
    REGION: str = "europe-west1"
    REPORTS_BUCKET: str = "sandbox-bsolano-migration-reports"
    DISCOVERY_JOB_NAME: str = "migration-discovery-job"
    SERVICE_URL: str = "http://localhost:8000"
    K_SERVICE: str = ""  # Populated by Cloud Run automatically

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_local(self) -> bool:
        """Determines if the application is running locally (not in Cloud Run)."""
        return not bool(self.K_SERVICE)


settings = Settings()


def get_settings() -> Settings:
    """Dependency provider for FastAPI injection."""
    return settings
