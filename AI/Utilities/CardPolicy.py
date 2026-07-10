"""Play policy: cards the bot should NOT cast yet because they trigger an
in-resolution card chooser (graveyard / exile / library / revealed hand) that
the bot cannot click through, which stalls the game.

Remove entries here as those choosers get implemented. Two layers, manual-first:
  1. UNSUPPORTED_GRP_IDS  -- exact grpIds, always block.
  2. oracle-text patterns -- catch the common phrasings automatically.
"""

from __future__ import annotations

import re

import AI.Utilities.CardInfo as CardInfo

# Exact grpIds we never cast for now (manual override / guaranteed catch).
UNSUPPORTED_GRP_IDS: set[int] = {
    93756,  # Inspiration from Beyond -- return an instant/sorcery from graveyard
}

# Oracle-text patterns for effects that pop an unclickable card chooser during
# resolution. Kept conservative: a "choose one" (a/an/one/... but not "target")
# from a hidden zone. Extend as we hit more.
_UNSUPPORTED_PATTERNS = [
    # "return an instant or sorcery card from your graveyard to your hand", etc.
    # The negative lookahead excludes "return target ... from your graveyard".
    re.compile(
        r"return\s+(?:a|an|one|two|three|up to \w+)\b(?:(?!target).)*?\bfrom (?:your )?graveyard\b",
        re.I | re.S,
    ),
]


def is_unsupported_to_cast(grp_id) -> bool:
    """True if we should skip casting this card (unimplemented chooser)."""
    if grp_id is None:
        return False
    try:
        grp_id = int(grp_id)
    except Exception:
        return False
    if grp_id in UNSUPPORTED_GRP_IDS:
        return True
    try:
        text = CardInfo.get_oracle_text(grp_id) or ""
    except Exception:
        return False
    if not text:
        return False
    t = text.replace("\n", " ")
    return any(pattern.search(t) for pattern in _UNSUPPORTED_PATTERNS)
