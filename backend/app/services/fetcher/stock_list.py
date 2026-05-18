import json
import yaml
import requests
from pathlib import Path
from app.config import settings

ELECTRONIC_INDUSTRIES = {
    "電子工業", "電子零組件業", "其他電子業", "其他電子類",
    "光電業", "電腦及週邊設備業", "電子通路業", "半導體業",
}


def load_sector_tags() -> dict[str, list[str]]:
    path = Path(settings.config_path) / "sector_tags.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("tags", {})


def load_all_tags() -> list[str]:
    path = Path(settings.config_path) / "sector_tags.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("all_tags", [])


async def fetch_electronic_stocks() -> list[dict]:
    """
    FinMind TaiwanStockInfo — 電子類股清單（上市+上櫃）
    過濾 ELECTRONIC_INDUSTRIES，搭配 sector_tags.yaml 加子族群標籤
    """
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockInfo"},
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = r.json().get("data", [])
    except Exception:
        return []

    tags_map = load_sector_tags()
    seen = set()
    rows = []
    for item in data:
        industry = item.get("industry_category", "")
        if industry not in ELECTRONIC_INDUSTRIES:
            continue
        code = item.get("stock_id", "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        market = "TWSE" if item.get("type") == "twse" else "TPEx"
        rows.append({
            "code": code,
            "name": item.get("stock_name", "").strip(),
            "market": market,
            "sector": industry,
            "tags": json.dumps(tags_map.get(code, []), ensure_ascii=False),
        })
    return rows
