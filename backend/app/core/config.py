from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "sqlite:///./ed.db"
    upload_dir: str = "./uploads"
    max_upload_mb: int = 50
    ocr_engine: str = "auto"
    class Config:
        env_file = ".env"

settings = Settings()
