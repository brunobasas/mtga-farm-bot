"""Pump-fight logic: spells that buff one of our creatures and then have it deal
damage equal to its power to an enemy creature (no retaliation).

Example -- Felling Blow: "Put a +1/+1 counter on target creature you control.
Then that creature deals damage equal to its power to target creature an
opponent controls."

These are TWO-target spells (our creature + an enemy creature). Policy:
  * buff our highest-power creature (max damage; the counter is pure upside and
    there is no retaliation, so no risk);
  * kill the best (highest-toughness) enemy creature we can with
    `our_power + counter` damage;
  * only cast when such a pairing exists.

`get_fight_profile(grp_id)` resolves a profile (manual table first, then oracle).
`choose_fight_pairing(...)` returns (our_creature_id, enemy_creature_id) or None.
"""

from __future__ import annotations

import re

import AI.Utilities.CardInfo as CardInfo
import AI.Utilities.RemovalLogic as RemovalLogic

# Manual overrides: grpId -> {"kind": "pump_fight", "counter": N}.
MANUAL_PROFILES: dict[int, dict] = {
    93818: {"kind": "pump_fight", "counter": 1},  # Felling Blow (Foundations)
}

# "Put a +N/+M counter on target creature you control. Then that creature deals
#  damage equal to its power to target creature an opponent controls."
_RE_PUMP_FIGHT = re.compile(
    r"put a \+(\d+)/\+\d+ counter on target creature you control"
    r".*?deals? damage equal to its power to (?:another )?target creature",
    re.I | re.S,
)


def get_fight_profile(grp_id) -> dict | None:
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
    m = _RE_PUMP_FIGHT.search(text.replace("\n", " "))
    if m:
        return {"kind": "pump_fight", "counter": int(m.group(1))}
    return None


def our_creatures(
    game_objects: list[dict], my_seat: int, battlefield_zone_ids: set[int] | None = None
) -> list[dict]:
    out = []
    for obj in game_objects or []:
        if not isinstance(obj, dict):
            continue
        if "CardType_Creature" not in (obj.get("cardTypes") or []):
            continue
        if obj.get("controllerSeatId") != my_seat:
            continue
        if battlefield_zone_ids is not None and obj.get("zoneId") not in battlefield_zone_ids:
            continue
        if obj.get("instanceId") is None:
            continue
        out.append(obj)
    return out


def _damage_from(creature: dict, counter: int) -> int:
    return RemovalLogic._stat(creature.get("power")) + int(counter)


def killable_by_damage(enemy: dict, damage: int) -> bool:
    """True if `damage` combat damage would destroy `enemy` (indestructible
    survives; equal-to-toughness damage is lethal)."""
    kws = RemovalLogic._creature_keywords(enemy)
    if "indestructible" in kws:
        return False
    return RemovalLogic.effective_toughness(enemy) <= int(damage)


def choose_fight_pairing(
    profile: dict,
    game_objects: list[dict],
    my_seat: int,
    battlefield_zone_ids: set[int] | None = None,
) -> tuple[int, int] | None:
    """(our_creature_id, enemy_creature_id) killing the best enemy, or None."""
    if not profile:
        return None
    counter = int(profile.get("counter", 1))
    ours = our_creatures(game_objects, my_seat, battlefield_zone_ids)
    if not ours:
        return None
    enemies = RemovalLogic.opponent_creatures(game_objects, my_seat, battlefield_zone_ids)
    if not enemies:
        return None
    # Buff the highest-power creature -> most damage.
    best_our = max(ours, key=lambda c: RemovalLogic._stat(c.get("power")))
    damage = _damage_from(best_our, counter)
    killable = [e for e in enemies if killable_by_damage(e, damage)]
    if not killable:
        return None
    best_enemy = max(
        killable,
        key=lambda c: (RemovalLogic.effective_toughness(c), RemovalLogic._stat(c.get("power"))),
    )
    return (int(best_our["instanceId"]), int(best_enemy["instanceId"]))
