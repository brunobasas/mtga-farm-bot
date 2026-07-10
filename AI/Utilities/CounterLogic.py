"""Counterspell logic: decide when to cast a counter in response to an
opponent's spell on the stack.

A counterspell is described by a *counter profile*:
  {"restrict": "creature"}     -- counters only creature spells (Essence Scatter)
  {"restrict": "noncreature"}  -- counters only noncreature spells
  {"restrict": "any"}          -- counters any spell

Profiles are resolved manual-first (MANUAL_PROFILES), then auto-detected from
the card's oracle text.

Usage (AI side): when we hold priority and the opponent has a spell on the
stack that one of our in-hand counters can counter, cast that counter. The
target (the spell on the stack) is then chosen by the Controller's target
selection in response to MTGA's SelectTargetsReq.
"""

from __future__ import annotations

import re

import AI.Utilities.CardInfo as CardInfo

# Manual overrides: grpId -> {"restrict": "creature"|"noncreature"|"any"}.
MANUAL_PROFILES: dict[int, dict] = {
    # Essence Scatter (Foundations printing) -- "Counter target creature spell."
    # Auto-detected from oracle text; pinned here as an offline safety net.
    93866: {"restrict": "creature"},
}

_RE_COUNTER_CREATURE = re.compile(r"counter target creature spell", re.I)
_RE_COUNTER_NONCREATURE = re.compile(r"counter target noncreature spell", re.I)
# "counter target spell" but not "...creature spell" / "...ability".
_RE_COUNTER_ANY = re.compile(r"counter target spell", re.I)


def get_counter_profile(grp_id) -> dict | None:
    """Resolve a counter profile for a card, or None if it is not a counter."""
    if grp_id is None:
        return None
    try:
        grp_id = int(grp_id)
    except Exception:
        return None
    if grp_id in MANUAL_PROFILES:
        return dict(MANUAL_PROFILES[grp_id])
    text = ""
    try:
        text = CardInfo.get_oracle_text(grp_id) or ""
    except Exception:
        text = ""
    if not text:
        return None
    t = text.replace("\n", " ")
    if _RE_COUNTER_CREATURE.search(t):
        return {"restrict": "creature"}
    if _RE_COUNTER_NONCREATURE.search(t):
        return {"restrict": "noncreature"}
    if _RE_COUNTER_ANY.search(t):
        return {"restrict": "any"}
    return None


def stack_zone_ids(full_state: dict) -> set[int]:
    ids: set[int] = set()
    for zone in (full_state.get("zones", []) or []):
        if zone.get("type") == "ZoneType_Stack" and zone.get("zoneId") is not None:
            ids.add(zone.get("zoneId"))
    return ids


def _stack_order(full_state: dict, stack_ids: set[int]) -> list[int]:
    """Ordered instanceIds on the stack (bottom -> top)."""
    order: list[int] = []
    for zone in (full_state.get("zones", []) or []):
        if zone.get("zoneId") in stack_ids:
            order.extend(zone.get("objectInstanceIds", []) or [])
    return order


def opponent_spells_on_stack(
    game_objects: list[dict], my_seat: int, stack_ids: set[int]
) -> list[dict]:
    out = []
    for obj in game_objects or []:
        if not isinstance(obj, dict):
            continue
        if obj.get("zoneId") not in stack_ids:
            continue
        if obj.get("controllerSeatId") == my_seat:
            continue
        if obj.get("instanceId") is None:
            continue
        out.append(obj)
    return out


def can_counter(profile: dict, stack_obj: dict) -> bool:
    types = stack_obj.get("cardTypes") or []
    is_creature = "CardType_Creature" in types
    restrict = profile.get("restrict")
    if restrict == "creature":
        return is_creature
    if restrict == "noncreature":
        return not is_creature
    return True


def find_counterable_spell(
    profile: dict,
    game_objects: list[dict],
    my_seat: int,
    stack_ids: set[int],
    full_state: dict | None = None,
) -> int | None:
    """Return the instanceId of the topmost opponent spell this counter can
    counter, or None. Topmost = last to have entered the stack (resolves first)."""
    spells = {
        obj["instanceId"]: obj
        for obj in opponent_spells_on_stack(game_objects, my_seat, stack_ids)
    }
    if not spells:
        return None
    order = _stack_order(full_state or {}, stack_ids)
    ordered_ids = [iid for iid in order if iid in spells] or list(spells)
    # Walk from the top of the stack down to the first counterable spell.
    for iid in reversed(ordered_ids):
        if can_counter(profile, spells[iid]):
            return int(iid)
    return None
