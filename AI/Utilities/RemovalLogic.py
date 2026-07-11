"""Targeted-removal logic shared by the AI (cast decision) and the Controller
(target selection).

A spell/ability that can target an enemy creature (or, for burn, the face) is
described by a *removal profile*. Profiles are resolved manual-first:

  1. `MANUAL_PROFILES[grpId]`  -- hand-authored override, always wins.
  2. auto-detection from the card's oracle text  -- covers the common patterns.

`choose_removal_target(profile, board, my_seat, opponent_life)` returns:
  *  -1 (`FACE_TARGET`)     -> aim at the opponent's face (lethal burn),
  *  a positive instanceId  -> aim at that enemy creature,
  *  None                   -> no good target; the caller must NOT cast it.

Policy (agreed in design):
  * creature target = the killable enemy creature with the highest *effective*
    toughness (current toughness minus marked damage), power as a tiebreak.
  * "killable" is evaluated with safeguards: indestructible survives `destroy`
    and `damage` (but not `-X/-X` reducing toughness to 0, nor `exile`);
    a deathtouch damage source kills with any amount.
  * dual-mode burn (can hit face or creature): if it is lethal to the face,
    go face; otherwise kill the best creature it can; otherwise don't cast.
"""

from __future__ import annotations

import re

import AI.Utilities.CardInfo as CardInfo

# Sentinel target: the opponent's face/avatar. Matches the Controller's existing
# convention where select_target(-1) clicks the opponent avatar.
FACE_TARGET = -1


# --- Layer 1a: manual overrides (grpId -> profile). Always take precedence. ---
# kinds:
#   {"kind": "damage", "amount": N, "can_hit_creature": bool, "can_hit_face": bool}
#   {"kind": "minus_toughness", "amount": N}   target creature gets -x/-N
#   {"kind": "destroy"}                          destroy target creature
#   {"kind": "exile"}                            exile target creature
# optional flag: "source_deathtouch": True       any damage is lethal
MANUAL_PROFILES: dict[int, dict] = {
    # Fill grpIds as we review cards one by one, e.g.:
    # 12345: {"kind": "minus_toughness", "amount": 2},   # Moment of Craving
    #
    # Bake into a Pie -- "Destroy target creature. Create a Food token."
    # Auto-detection now resolves this from oracle text (the real bug was the
    # missing Accept header on Scryfall requests, see CardInfo._SCRYFALL_HEADERS).
    # Kept as an offline safety net: the local card DB has no oracle text, so with
    # no network only these manual profiles work.
    93882: {"kind": "destroy"},
}


def get_removal_profile(grp_id: int | None) -> dict | None:
    """Resolve a removal profile for a card: manual table first, else oracle."""
    if grp_id is None:
        return None
    try:
        grp_id = int(grp_id)
    except Exception:
        return None
    if grp_id in MANUAL_PROFILES:
        return dict(MANUAL_PROFILES[grp_id])
    return detect_profile_from_oracle(grp_id)


# --- Self-target pump/protect tricks ---
# These must be cast on one of OUR creatures, never an enemy's (that would buff
# the opponent) and never the avatar. "target creature" spells also list enemy
# creatures as legal, so without this the generic path would hand the buff to the
# opponent or stall on the illegal avatar. Fake Your Own Death across all its
# printings, plus an oracle heuristic for other "+N/+M" pump tricks.
SELF_BUFF_GRPIDS: set[int] = {80230, 90433, 92991, 93887}

_RE_SELF_BUFF = re.compile(r"target creature gets \+\d+/", re.I)


def is_self_buff(grp_id) -> bool:
    """True if the card is a pump/protect trick to cast on our own creature."""
    if grp_id is None:
        return False
    try:
        grp_id = int(grp_id)
    except Exception:
        return False
    if grp_id in SELF_BUFF_GRPIDS:
        return True
    # A card that is removal is not a self-buff, even if its text mentions a buff.
    if get_removal_profile(grp_id):
        return False
    try:
        text = str(CardInfo.get_oracle_text(grp_id) or "")
    except Exception:
        return False
    return bool(_RE_SELF_BUFF.search(text))


# --- Layer 1b: auto-detection from oracle text ---
_CREATURE_TARGET = r"target (?:attacking |blocking |tapped |untapped )?creature"

_RE_DESTROY = re.compile(r"destroy " + _CREATURE_TARGET, re.I)
_RE_EXILE = re.compile(r"exile " + _CREATURE_TARGET, re.I)
# "target creature ... gets -X/-Y"
_RE_MINUS = re.compile(_CREATURE_TARGET + r"[^.]*?gets\s*[+-]?\d+/(-\d+)", re.I)
# "deals N damage to <target phrase>"
_RE_DAMAGE = re.compile(r"deals?\s+(\d+)\s+damage\s+to\s+([^.;]+)", re.I)


def _analyze_damage_targets(phrase: str) -> tuple[bool, bool]:
    """(can_hit_creature, can_hit_face) for a damage target phrase.

    "any target" covers creature, player, and planeswalker. Otherwise we look
    for the words themselves; "planeswalker" is not the face.
    """
    p = phrase.lower()
    if "any target" in p:
        return True, True
    hits_creature = "creature" in p
    hits_face = ("player" in p) or ("opponent" in p)
    return hits_creature, hits_face


def detect_profile_from_oracle(grp_id: int) -> dict | None:
    text = ""
    try:
        text = CardInfo.get_oracle_text(grp_id) or ""
    except Exception:
        text = ""
    if not text:
        return None
    t = text.replace("\n", " ")

    # Prefer the unconditional kill if a card does several things.
    if _RE_EXILE.search(t):
        return {"kind": "exile"}
    if _RE_DESTROY.search(t):
        return {"kind": "destroy"}

    m = _RE_MINUS.search(t)
    if m:
        amount = abs(int(m.group(1)))
        if amount > 0:
            return {"kind": "minus_toughness", "amount": amount}

    m = _RE_DAMAGE.search(t)
    if m:
        hits_creature, hits_face = _analyze_damage_targets(m.group(2))
        if hits_creature or hits_face:
            profile = {
                "kind": "damage",
                "amount": int(m.group(1)),
                "can_hit_creature": hits_creature,
                "can_hit_face": hits_face,
            }
            if _source_has_deathtouch(grp_id, text):
                profile["source_deathtouch"] = True
            return profile

    return None


def _source_has_deathtouch(grp_id: int, oracle_text: str) -> bool:
    try:
        info = CardInfo.get_card_info(grp_id) or {}
        kws = [str(k).lower() for k in (info.get("keywords") or [])]
        if "deathtouch" in kws:
            return True
    except Exception:
        pass
    return "deathtouch" in (oracle_text or "").lower()


# --- Layer 2: board evaluation ---
def _stat(value) -> int:
    if isinstance(value, dict):
        try:
            return int(value.get("value", 0) or 0)
        except Exception:
            return 0
    try:
        return int(value or 0)
    except Exception:
        return 0


def effective_toughness(creature: dict) -> int:
    """Current toughness minus marked damage."""
    return _stat(creature.get("toughness")) - _stat(creature.get("damage"))


# Creatures whose death is beneficial or who recur from the graveyard -- ideal
# to feed to a sacrifice cost (e.g. Eaten Alive). Manual pins plus an oracle
# heuristic so it generalizes.
_SAC_FODDER_GRPIDS = {
    93777,                # Infestation Sage (dies -> token)
    93776,                # Infernal Vessel (dies -> returns upgraded)
    67912, 93032, 93895,  # Reassembling Skeleton (graveyard recursion)
}


def is_sacrifice_fodder(grp_id) -> bool:
    """True if sacrificing this creature is (near) free -- a beneficial death
    trigger or graveyard recursion."""
    if grp_id is None:
        return False
    try:
        grp_id = int(grp_id)
    except Exception:
        return False
    if grp_id in _SAC_FODDER_GRPIDS:
        return True
    try:
        info = CardInfo.get_card_info(grp_id) or {}
    except Exception:
        return False
    text = str(info.get("oracleText") or "").lower()
    return "this creature dies" in text or "from your graveyard" in text


def _creature_keywords(creature: dict) -> set[str]:
    """Printed keywords for the creature's card (best-effort; keywords granted
    by other effects are not visible here)."""
    grp_id = creature.get("grpId")
    if grp_id is None:
        return set()
    try:
        info = CardInfo.get_card_info(grp_id) or {}
    except Exception:
        return set()
    kws = {str(k).lower() for k in (info.get("keywords") or [])}
    oracle = str(info.get("oracleText") or "").lower()
    for kw in ("indestructible", "protection", "hexproof", "shroud"):
        if kw in oracle:
            kws.add(kw)
    return kws


def can_kill(profile: dict, creature: dict) -> bool:
    kind = profile.get("kind")
    kws = _creature_keywords(creature)

    if kind == "exile":
        # Exile ignores indestructible; MTGA would not offer an illegal target.
        return True

    if kind == "destroy":
        return "indestructible" not in kws

    if kind == "minus_toughness":
        # Toughness <= 0 is a state-based kill; indestructible does NOT save it.
        return effective_toughness(creature) <= int(profile.get("amount", 0))

    if kind == "damage":
        if "indestructible" in kws:
            return False
        if profile.get("source_deathtouch"):
            return True
        return effective_toughness(creature) <= int(profile.get("amount", 0))

    return False


def opponent_creatures(
    game_objects: list[dict],
    my_seat: int,
    battlefield_zone_ids: set[int] | None = None,
) -> list[dict]:
    out = []
    for obj in game_objects or []:
        if not isinstance(obj, dict):
            continue
        if "CardType_Creature" not in (obj.get("cardTypes") or []):
            continue
        if obj.get("controllerSeatId") == my_seat:
            continue
        if battlefield_zone_ids is not None and obj.get("zoneId") not in battlefield_zone_ids:
            continue
        if obj.get("instanceId") is None:
            continue
        out.append(obj)
    return out


def opponent_life_from_players(players: list[dict], my_seat: int) -> int | None:
    """Lowest life total among opponents (seats other than my_seat)."""
    best = None
    for pl in players or []:
        if not isinstance(pl, dict):
            continue
        seat = pl.get("systemSeatNumber")
        if seat is None or seat == my_seat:
            continue
        life = pl.get("lifeTotal", pl.get("life"))
        if life is None:
            continue
        try:
            life = int(life)
        except Exception:
            continue
        best = life if best is None else min(best, life)
    return best


def choose_removal_target(
    profile: dict,
    game_objects: list[dict],
    my_seat: int,
    opponent_life: int | None = None,
    battlefield_zone_ids: set[int] | None = None,
) -> int | None:
    """FACE_TARGET (-1) for lethal burn, a creature instanceId, or None."""
    if not profile:
        return None
    kind = profile.get("kind")

    # Dual-mode burn: prefer lethal to the face.
    if kind == "damage" and profile.get("can_hit_face") and opponent_life is not None:
        try:
            if int(opponent_life) <= int(profile.get("amount", 0)):
                return FACE_TARGET
        except Exception:
            pass

    # Burn that cannot hit creatures has no creature fallback.
    if kind == "damage" and not profile.get("can_hit_creature", True):
        return None

    enemies = opponent_creatures(game_objects, my_seat, battlefield_zone_ids)
    killable = [c for c in enemies if can_kill(profile, c)]
    if not killable:
        return None
    best = max(killable, key=lambda c: (effective_toughness(c), _stat(c.get("power"))))
    return int(best["instanceId"])
