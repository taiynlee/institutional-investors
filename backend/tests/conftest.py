import pathlib
from app.config import settings

# tests/ → backend/ → institutional-investors/ → config/
_CONFIG_PATH = str(pathlib.Path(__file__).parents[2] / "config")
settings.config_path = _CONFIG_PATH
