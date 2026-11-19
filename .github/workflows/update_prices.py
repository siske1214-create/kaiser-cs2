"""Собирает цены и пишет prices.json в корень репозитория.

Источники: цены Steam Community Market (из открытого файла csgotrader) — они в приоритете;
если предмета там нет или файл недоступен, берётся Skinport × PRICE_FACTOR.

Формат: {"updated": "...", "source": "steam+skinport",
         "p": {"ak47redline": 12.34, ...},      # цена «После полевых» (у предметов без износа — просто цена)
         "m": {"ak47redline": [3.1, 1.6, 1, 0.7, 0.5], ...}}  # множители износов к «После полевых»: FN, MW, FT, WW, BS
Ключ = название в нижнем регистре без ★, StatTrak™, износа и знаков (как norm() в игре).
Если реальной цены для какого-то износа нет, в "m" стоит null, и игра берёт обычный множитель.
"""
import json, os, re, sys
from datetime import datetime, timezone

import requests  # для расшифровки ответа Skinport (br) нужен пакет brotli

# порядок как WEARS в index.html: FN, MW, FT, WW, BS; запасные множители — оттуда же
WEAR_ORDER = ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]
DEFAULT = {"Factory New": 1.6, "Minimal Wear": 1.2, "Field-Tested": 1.0,
           "Well-Worn": 0.8, "Battle-Scarred": 0.7}
PREFER = ["Field-Tested", "Minimal Wear", "Well-Worn", "Battle-Scarred", "Factory New"]
SKIP = ("Patch |", "Sealed Graffiti |", "Graffiti |", "Charm |")
FACTOR = float(os.environ.get("PRICE_FACTOR", "1"))  # Skinport обычно дешевле Steam; поправка к ценам Steam


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9а-я]", "", s.lower())


def fetch_skinport() -> dict:
    try:
        r = requests.get(
            "https://api.skinport.com/v1/items",
            params={"app_id": 730, "currency": "USD"},
            headers={"Accept-Encoding": "br", "User-Agent": "cs2-sim-price-updater"},
            timeout=120,
        )
        r.raise_for_status()
        out = {}
        for it in r.json():
            price = it.get("median_price") or it.get("min_price") or it.get("suggested_price")
            if it.get("market_hash_name") and price and price > 0:
                out[it["market_hash_name"]] = float(price)
        return out
    except Exception as e:  # noqa: BLE001
        print("Skinport недоступен:", e)
        return {}


def fetch_steam() -> dict:
    """Цены Steam Market (USD): последние 7 дней, иначе 30/90/24 ч."""
    try:
        r = requests.get("https://prices.csgotrader.app/latest/prices_v6.json",
                         headers={"User-Agent": "cs2-sim-price-updater"}, timeout=300)
        r.raise_for_status()
        out = {}
        for name, v in r.json().items():
            st = v.get("steam") if isinstance(v, dict) else None
            if isinstance(st, dict):
                for k in ("last_7d", "last_30d", "last_90d", "last_24h"):
                    x = st.get(k)
                    if isinstance(x, (int, float)) and x > 0:
                        out[name] = float(x)
                        break
        return out
    except Exception as e:  # noqa: BLE001
        print("csgotrader (цены Steam) недоступен:", e)
        return {}


def main() -> None:
    sp, st = fetch_skinport(), fetch_steam()
    print(f"Skinport: {len(sp)}, Steam: {len(st)}")
    price_of = {n: (st[n] if n in st else sp[n] * FACTOR) for n in set(sp) | set(st)}

    skins, plain = {}, {}  # ключ -> {износ: цена}; ключ -> цена (без износа)
    for name, price in price_of.items():
        if "StatTrak" in name or name.startswith("Souvenir") or " | " not in name:
            continue
        if name.startswith(SKIP):
            continue
        m = re.search(r"\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)$", name)
        if m:
            key = norm(name[: m.start()].replace("★", ""))
            if key:
                skins.setdefault(key, {})[m.group(1)] = price
        else:  # агенты, музыка, наклейки и т.п.
            key = norm(name.replace("★", ""))
            if key:
                plain[key] = price

    p_out, m_out = {}, {}
    for key, d in skins.items():
        first = next(w for w in PREFER if w in d)
        base = d[first] / DEFAULT[first]  # цена «После полевых» (настоящая или пересчитанная)
        p_out[key] = round(base, 2)
        if len(d) >= 2:
            ratios = []
            for w in WEAR_ORDER:
                v = d[w] / base if w in d else None
                ratios.append(round(v, 3) if v is not None and 0.05 <= v <= 60 else None)
            m_out[key] = ratios
    for key, v in plain.items():
        p_out.setdefault(key, round(v, 2))

    if len(p_out) < 500:
        sys.exit(f"Слишком мало цен ({len(p_out)}), prices.json не трогаю")

    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "steam+skinport",
        "p": dict(sorted(p_out.items())),
        "m": dict(sorted(m_out.items())),
    }
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Записано цен: {len(p_out)}, с ценами по износам: {len(m_out)}, наклеек: {sum(1 for k in p_out if k.startswith('sticker'))}")


if __name__ == "__main__":
    main()
