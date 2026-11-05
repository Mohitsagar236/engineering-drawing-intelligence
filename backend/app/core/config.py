from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./ed.db"
    upload_dir: str = "./uploads"
    max_upload_mb: int = Field(default=50, ge=1, le=200)
    max_pages: int = Field(default=50, ge=1, le=500)
    max_image_pixels: int = Field(default=25_000_000, ge=1, le=100_000_000)
    render_dpi: int = Field(default=180, ge=72, le=300)
    ocr_engine: Literal["easyocr", "paddleocr", "auto"] = "easyocr"
    ocr_languages: str = "en"
    ocr_min_confidence: float = Field(default=0.9, ge=0, le=1)
    cors_origins: str = "http://localhost:3000"
    environment: Literal["development", "production", "test"] = "development"
    auth_username: str = Field(default="reviewer", min_length=1, max_length=100)
    auth_password: str = ""
    processing_timeout: int = Field(default=600, ge=10, le=3600)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def production_configuration(self):
        if self.environment == "production":
            if len(self.auth_password) < 16 or not self.auth_username.strip():
                raise ValueError(
                    "Production requires an AUTH_USERNAME and AUTH_PASSWORD of at least 16 characters"
                )
            if not self.cors_origin_list:
                raise ValueError("Production requires an explicit HTTPS CORS_ORIGINS")
            for origin in self.cors_origin_list:
                url = urlsplit(origin)
                if (
                    url.scheme != "https"
                    or "*" in origin
                    or not url.hostname
                    or url.username
                    or url.password
                    or url.path
                    or url.query
                    or url.fragment
                ):
                    raise ValueError(
                        "Production CORS_ORIGINS must contain HTTPS origins without paths or wildcards"
                    )
        return self

    @property
    def cors_origin_list(self):
        return [v.strip() for v in self.cors_origins.split(",") if v.strip()]


settings = Settings()
