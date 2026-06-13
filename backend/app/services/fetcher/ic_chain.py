"""
產業價值鏈分類爬蟲：從 ic.tpex.org.tw 抓取電子科技相關產業的公司清單。
每月更新一次即可，產業歸屬變動頻率極低。
"""

import asyncio
import logging
import re
import httpx
from bs4 import BeautifulSoup
from datetime import datetime

logger = logging.getLogger(__name__)

IC_TARGETS: list[tuple[str, str, str | None]] = [
    ("D000", "半導體",      None),
    ("I000", "通信網路",    None),
    ("J000", "被動元件",    None),
    ("K000", "連接器",      None),
    ("F000", "電腦週邊",    None),
    ("G000", "平面顯示器",  None),
    ("H000", "觸控面板",    None),
    ("L000", "印刷電路板",  None),
    ("6000", "自動化",      None),
    ("R000", "軟體服務",    None),
    ("5300", "人工智慧",    "數位科技"),
    ("5400", "雲端運算",    "數位科技"),
    ("5500", "資通訊安全",  "數位科技"),
    ("5100", "區塊鏈",      "數位科技"),
    ("5200", "金融科技",    "數位科技"),
    ("5600", "大數據",      "數位科技"),
    ("4100", "太空衛星科技","前瞻科技"),
]

BASE_URL = "https://ic.tpex.org.tw/introduce.php?ic={ic_code}"
_NOISE = re.compile(r"產業鏈|簡介|介紹|首頁|更多|回上頁|關於")


def _extract_name(a_tag) -> str | None:
    raw = a_tag.get_text(strip=True)
    candidate = re.sub(r"^\d{4,6}\s*", "", raw).strip()
    return candidate if candidate and not _NOISE.search(candidate) else None


def _parse_page(html: str, ic_code: str, ic_name: str, ic_parent: str | None) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    noscript = soup.find("noscript")
    if not noscript:
        logger.warning(f"ic_chain {ic_code}: no <noscript> found")
        return []

    rows: list[dict] = []
    seen: set[str] = set()
    now = datetime.utcnow()

    for outer in noscript.find_all("div", recursive=False):
        company_list = outer.find("div", class_="company-list")
        subchain_list = outer.find("div", class_="subchain-company-list")
        inner = company_list or subchain_list
        if not inner:
            continue

        if subchain_list:
            b = subchain_list.find("b")
            node_name = b.get_text(strip=True) if b else None
        else:
            full = company_list.get_text(strip=True)
            m = re.match(r"^(.+?)(?:本國|外國|知名)", full)
            node_name = m.group(1).strip() if m else None

        if not node_name:
            continue

        for a in inner.find_all("a", href=re.compile(r"stk_code=")):
            cm = re.search(r"stk_code=(\w+)", a["href"])
            if not cm:
                continue
            code = cm.group(1).strip()
            if not re.fullmatch(r"\d{4,6}", code):
                continue
            if code in seen:
                continue
            seen.add(code)
            rows.append({
                "code":       code,
                "name":       _extract_name(a),
                "ic_code":    ic_code,
                "ic_name":    ic_name,
                "ic_parent":  ic_parent,
                "ic_node":    node_name,
                "ic_position": None,
                "updated_at": now,
            })

    logger.info(f"ic_chain {ic_code}({ic_name}): {len(rows)} companies")
    return rows


async def fetch_ic_chain(ic_code: str, ic_name: str, ic_parent: str | None,
                         client: httpx.AsyncClient) -> list[dict]:
    url = BASE_URL.format(ic_code=ic_code)
    try:
        resp = await client.get(url, timeout=20)
        resp.raise_for_status()
        return _parse_page(resp.text, ic_code, ic_name, ic_parent)
    except Exception as e:
        logger.warning(f"ic_chain fetch failed for {ic_code}: {e}")
        return []


async def fetch_all_ic_chains() -> list[dict]:
    all_rows: list[dict] = []
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for ic_code, ic_name, ic_parent in IC_TARGETS:
            rows = await fetch_ic_chain(ic_code, ic_name, ic_parent, client)
            all_rows.extend(rows)
            await asyncio.sleep(1)
    logger.info(f"ic_chain total: {len(all_rows)} rows across {len(IC_TARGETS)} chains")
    return all_rows
