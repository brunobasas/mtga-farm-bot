"""Lifegain-payoff detection for the Orzhov starter deck.

The deck's engine is "gain life -> a creature grows". The payoff creatures all
share one oracle line:

    Whenever you gain life, put a +1/+1 counter on this creature.

(Ajani's Pridemate, Twinblade Paladin, Fiendish Panda.) Their value is almost
entirely a function of how many lifegain triggers they are on the board FOR, so
a turn spent not having one out is a turn of counters lost forever. That is why
the AI casts them ahead of other creatures of the same plan.

Detection is by oracle text rather than a grpId table on purpose: the deck data
holds four printings of Ajani's Pridemate and two of Twinblade Paladin (93447,
93848, 69455, 67690 / 70069, 93652), and a hand-maintained list silently misses
the next reprint. GRPIDS below is only an offline fallback for when Scryfall is
unreachable and the local DB carries no oracle text.
"""

from __future__ import annotations

import re

import AI.Utilities.CardInfo as CardInfo

# Offline safety net only -- detection normally runs off oracle text. Printings
# present in data/starter_deck_cards.json as of 2026-07-20.
PAYOFF_GRPIDS: set[int] = {
    67690, 69455, 93447, 93848,  # Ajani's Pridemate
    70069, 93652,                # Twinblade Paladin
    93833,                       # Fiendish Panda
}

# "Whenever you gain life, put a +1/+1 counter on this creature." Deliberately
# not anchored on the counter clause: cards that do something else on lifegain
# still key off the same engine and still want to be deployed early.
_RE_LIFEGAIN_PAYOFF = re.compile(r"whenever you gain life", re.I)

_payoff_memo: dict[int, bool] = {}


def _payoff_lookup(grp_id: int) -> bool:
    if grp_id in PAYOFF_GRPIDS:
        return True
    if grp_id in _payoff_memo:
        return _payoff_memo[grp_id]
    try:
        text = str(CardInfo.get_oracle_text(grp_id) or "")
    except Exception:
        text = ""
    result = bool(_RE_LIFEGAIN_PAYOFF.search(text))
    if text:
        # Same rationale as RemovalLogic._removal_profile_lookup: only memoize
        # once real oracle text was available, so a transient Scryfall failure
        # does not permanently misclassify the card.
        _payoff_memo[grp_id] = result
    return result


def is_lifegain_payoff(grp_id) -> bool:
    """True if the card grows (or otherwise triggers) whenever we gain life."""
    if grp_id is None:
        return False
    try:
        grp_id = int(grp_id)
    except Exception:
        return False
    return _payoff_lookup(grp_id)
