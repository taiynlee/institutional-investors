from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://stock:secret@localhost:5432/stock_force"
    finmind_token: str = ""
    config_path: str = "/app/config"

    class Config:
        env_file = ".env"


settings = Settings()
