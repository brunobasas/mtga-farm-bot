"""Regenerate the curated Starter Deck Duel card database.

Starter Deck Duel only ever uses the ten Foundations Starter Decks, so the bot
does not need (and should not depend on) live data for all of Magic. This script
builds a small, committed dataset covering exactly those decks:

  data/starter_deck_cards.json  -- grpId -> {name, oracleText, types, ...} for
                                   every Arena printing of every card in the decks.
  data/starter_decks.json       -- deck name -> {card name: quantity}.

The MTGA export (cards.json) carries no oracle text, and the deck list lives on
the wiki, so both sources are combined here. Oracle text is fetched from
Scryfall (which now requires an Accept header, see CardInfo._SCRYFALL_HEADERS).

Run:  python tools/build_starter_deck_cards.py
Re-run whenever the Starter Deck Duel line-up changes.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

WIKI_URL = "https://mtg.wiki/page/Foundations_Starter_Decks"
# Scryfall rejects requests without both headers; a browser UA gets past the
# wiki's bot filter.
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
SCRYFALL_HEADERS = {"User-Agent": "MTGABot/1.0", "Accept": "application/json"}

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")

DECK_NAMES = [
    "Arcane Aerialists",
    "Cat Attack",
    "Graveyard Gifts",
    "Learn From the Land",
    "Might of the Legion",
    "Morbid Machinations",
    "Path of Power",
    "Reckless Raid",
    "Vampiric Hunger",
    "Wondrous Wizardry",
]


def fetch_wiki_html() -> str:
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_decks(page: str) -> dict[str, dict[str, int]]:
    """deck name -> {card name: quantity} from the wiki's Scryfall deck blocks."""
    anchors = []
    for name in DECK_NAMES:
        m = re.search(r'id="' + re.escape(name.replace(" ", "_")) + r'"', page)
        if m:
            anchors.append((name, m.start()))
    anchors.sort(key=lambda x: x[1])
    end_marker = page.find('id="References"')
    decks: dict[str, dict[str, int]] = {}
    for idx, (name, pos) in enumerate(anchors):
        end = anchors[idx + 1][1] if idx + 1 < len(anchors) else end_marker
        chunk = page[pos:end]
        entries = re.findall(
            r'deckcardcount">(\d+)</span>\s*<a[^>]*data-card-name="([^"]+)"', chunk
        )
        cards: dict[str, int] = {}
        for count, card in entries:
            cards[html.unescape(card)] = cards.get(html.unescape(card), 0) + int(count)
        decks[name] = cards
    return decks


def scryfall_prints(card_name: str, *, retries: int = 4) -> list[dict]:
    query = urllib.parse.quote(f'!"{card_name}" game:arena')
    url = f"https://api.scryfall.com/cards/search?q={query}&unique=prints"
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=SCRYFALL_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8")).get("data", [])
        except urllib.error.HTTPError as e:
            # 429 = rate limited: back off and retry. Anything else is real.
            if e.code == 429 and attempt < retries - 1:
                time.sleep(1.0 + attempt * 1.5)
                continue
            raise
    return []


def build_card_db(card_names: list[str]) -> tuple[dict, list]:
    by_grp: dict[str, dict] = {}
    failures: list = []
    for name in card_names:
        try:
            printings = scryfall_prints(name)
        except urllib.error.HTTPError as e:
            failures.append((name, e.code))
            continue
        except Exception as e:  # noqa: BLE001 - report and continue
            failures.append((name, str(e)))
            continue
        for card in printings:
            arena_id = card.get("arena_id")
            if arena_id is None:
                continue
            by_grp[str(arena_id)] = {
                "grpId": arena_id,
                "name": card.get("name"),
                "oracleText": card.get("oracle_text", "") or "",
                "types": card.get("type_line", "").replace("—", "-").split(),
                "manaCost": card.get("mana_cost", "") or "",
                "colors": card.get("colors", []),
                "keywords": card.get("keywords", []),
                "setCode": card.get("set", "").upper(),
            }
        time.sleep(0.2)  # be polite to Scryfall (stay well under the rate limit)
    return by_grp, failures


def main() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    print(f"Fetching {WIKI_URL} ...")
    page = fetch_wiki_html()
    decks = parse_decks(page)
    for name, cards in decks.items():
        print(f"  {name}: {len(cards)} unique / {sum(cards.values())} total")

    unique_names = sorted({card for cards in decks.values() for card in cards})
    print(f"Unique cards across all decks: {len(unique_names)}")

    by_grp, failures = build_card_db(unique_names)
    print(f"Arena printings collected: {len(by_grp)}")
    if failures:
        print(f"WARNING: {len(failures)} card(s) failed to resolve:")
        for f in failures:
            print("  ", f)

    decks_path = os.path.join(_DATA_DIR, "starter_decks.json")
    cards_path = os.path.join(_DATA_DIR, "starter_deck_cards.json")
    with open(decks_path, "w", encoding="utf-8") as f:
        json.dump(decks, f, ensure_ascii=False, indent=2)
    with open(cards_path, "w", encoding="utf-8") as f:
        json.dump(by_grp, f, ensure_ascii=False, indent=1)
    print(f"Wrote {decks_path}")
    print(f"Wrote {cards_path}")


if __name__ == "__main__":
    main()
