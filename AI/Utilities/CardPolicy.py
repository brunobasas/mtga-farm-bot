"""Play policy: cards the bot should NOT cast.

Two reasons a card lands here:
  * it triggers an in-resolution card chooser the bot cannot click through
    (would stall the game), or
  * it is a reactive card with no good proactive line, so casting it on our own
    turn just wastes it (STRATEGIC_SKIP_GRP_IDS).

Layers, manual-first:
  1. UNSUPPORTED_GRP_IDS / STRATEGIC_SKIP_GRP_IDS -- exact grpIds, always block.
  2. oracle-text patterns -- catch the common stall phrasings automatically.
"""

from __future__ import annotations

import re

import AI.Utilities.CardInfo as CardInfo

# Exact grpIds we never cast for now (manual override / guaranteed catch).
UNSUPPORTED_GRP_IDS: set[int] = {
    93756,  # Inspiration from Beyond -- return an instant/sorcery from graveyard
}

# Cards we deliberately never cast: reactive-only tricks with no reliable
# proactive line. Casting them on our turn wastes them.
STRATEGIC_SKIP_GRP_IDS: set[int] = {
    # Undying Malice -- "target creature gains 'when it dies, return it with a
    # +1/+1 counter'." Only worth it in response to removal targeting our
    # creature; that reactive read is too situational to automate reliably.
    78934, 93677,
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
    if grp_id in UNSUPPORTED_GRP_IDS or grp_id in STRATEGIC_SKIP_GRP_IDS:
        return True
    try:
        text = CardInfo.get_oracle_text(grp_id) or ""
    except Exception:
        return False
    if not text:
        return False
    t = text.replace("\n", " ")
    return any(pattern.search(t) for pattern in _UNSUPPORTED_PATTERNS)
