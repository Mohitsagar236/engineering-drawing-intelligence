from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./ed.db"
    upload_dir: str = "./uploads"
    max_upload_mb: int = 50
    ocr_engine: str = "auto"
    cors_origins: str = "http://localhost:3000"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def cors_origin_list(self):
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

settings = Settings()
