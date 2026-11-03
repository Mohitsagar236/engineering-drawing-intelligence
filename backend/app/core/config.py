from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./ed.db"
    upload_dir: str = "./uploads"
    max_upload_mb: int = Field(default=50, ge=1, le=200)
    max_pages: int = Field(default=50, ge=1, le=500)
    max_image_pixels: int = 25_000_000
    render_dpi: int = Field(default=180, ge=72, le=300)
    ocr_engine: Literal["easyocr", "paddleocr", "auto"] = "easyocr"
    ocr_languages: str = "en"
    ocr_min_confidence: float = Field(default=0.9, ge=0, le=1)
    cors_origins: str = "http://localhost:3000"
    environment: Literal["development", "production", "test"] = "development"
    auth_username: str = "reviewer"
    auth_password: str = ""
    processing_timeout: int = Field(default=600, ge=10, le=3600)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self):
        return [v.strip() for v in self.cors_origins.split(",") if v.strip()]


settings = Settings()
