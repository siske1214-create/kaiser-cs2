"""Собирает цены со Skinport и пишет prices.json в корень репозитория.

Формат: {"updated": "...", "source": "skinport", "p": {"ak47redline": 12.34, ...}}
Ключ = название скина в нижнем регистре без ★, StatTrak™, износа и знаков (как norm() в игре).
Цена = цена «После полевых» (так в игре хранится базовая цена), остальные износы считает игра.
"""
import json, os, re, sys
from datetime import datetime, timezone

import requests  # для расшифровки ответа Skinport (br) нужен пакет brotli

# множители износов — как WEARS в index.html (После полевых = 1)
WEARS = {"Factory New": 1.6, "Minimal Wear": 1.2, "Field-Tested": 1.0,
         "Well-Worn": 0.8, "Battle-Scarred": 0.7}
ORDER = ["Field-Tested", "Minimal Wear", "Well-Worn", "Battle-Scarred", "Factory New"]
SKIP = ("Sticker |", "Patch |", "Sealed Graffiti |", "Graffiti |", "Charm |")
FACTOR = float(os.environ.get("PRICE_FACTOR", "1"))  # поправка, если нужно приблизить к ценам Steam


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9а-я]", "", s.lower())


def main() -> None:
    r = requests.get(
        "https://api.skinport.com/v1/items",
        params={"app_id": 730, "currency": "USD"},
        headers={"Accept-Encoding": "br", "User-Agent": "cs2-sim-price-updater"},
        timeout=120,
    )
    r.raise_for_status()
    items = r.json()

    best = {}  # ключ -> (приоритет износа, цена в пересчёте на «После полевых»)
    for it in items:
        name = it.get("market_hash_name") or ""
        if "StatTrak" in name or name.startswith("Souvenir") or " | " not in name:
            continue
        if name.startswith(SKIP):
            continue
        price = it.get("median_price") or it.get("min_price")
        if not price or price <= 0:
            continue
        m = re.search(r"\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)$", name)
        if m:
            wear, base = m.group(1), name[: m.start()].strip()
            ft_price = price / WEARS[wear]
            prio = ORDER.index(wear)
        else:  # агенты, музыка и т.п. — без износа
            base, ft_price, prio = name, price, 0
        key = norm(base.replace("★", ""))
        if key and (key not in best or prio < best[key][0]):
            best[key] = (prio, ft_price)

    if len(best) < 500:
        sys.exit(f"Слишком мало цен ({len(best)}), prices.json не трогаю")

    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "skinport",
        "p": {k: round(v[1] * FACTOR, 2) for k, v in sorted(best.items())},
    }
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Записано цен: {len(best)}")


if __name__ == "__main__":
    main()
