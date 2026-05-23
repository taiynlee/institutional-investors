from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://stock:secret@localhost:5432/stock_force"
    finmind_token: str = ""
    config_path: str = "/app/config"
    line_bot_url: str = "http://172.17.0.1:8001"

    class Config:
        env_file = ".env"


settings = Settings()
