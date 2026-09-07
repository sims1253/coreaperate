"""Strict integer canonical model. Musical time = millionths of a quarter note."""
import hashlib
import json
import re

LIMIT = 1_048_576
ID = re.compile(r"^[A-Za-z0-9{}_-]{1,80}$")


class Invalid(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise Invalid(reason)


def ident(value):
    require(isinstance(value, str) and ID.fullmatch(value), "invalid identifier")
    return value


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, "integer out of range")


def keys(obj, names):
    require(type(obj) is dict and set(obj) == set(names.split()), "unexpected/missing fields")


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def loads(raw):
    require(len(raw.encode() if isinstance(raw, str) else raw) <= LIMIT, "message too large")
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "duplicate JSON key")
            result[k] = v
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite number")))
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise Invalid("invalid JSON") from exc


def digest(obj):
    return hashlib.sha256(dumps(obj).encode()).hexdigest()


def item(value):
    keys(value, "id take position length notes")
    ident(value["id"]); ident(value["take"])
    integer(value["position"], 0, 10**12)
    integer(value["length"], 1, 10**10)
    require(type(value["notes"]) is list and len(value["notes"]) <= 2048, "too many notes")
    for n in value["notes"]:
        require(type(n) is list and len(n) == 7, "note needs onset duration pitch velocity channel mute reserved")
        integer(n[0], 0, 10**10); integer(n[1], 1, 10**10)
        integer(n[2], 0, 127); integer(n[3], 1, 127); integer(n[4], 0, 15)
        integer(n[5], 0, 1); integer(n[6], 0, 0)
    require(value["notes"] == sorted(value["notes"]), "notes must be sorted")


def track(value):
    keys(value, "id name volume pan items")
    ident(value["id"])
    require(type(value["name"]) is str and len(value["name"].encode()) <= 512 and '\x00' not in value["name"], "invalid track name")
    integer(value["volume"], 0, 16_000_000); integer(value["pan"], -1_000_000, 1_000_000)
    require(type(value["items"]) is dict and len(value["items"]) <= 64, "too many items")
    for k, v in value["items"].items():
        item(v); require(k == v["id"], "item key mismatch")


def project(value):
    keys(value, "session config tracks order")
    ident(value["session"])
    keys(value["config"], "tempo numerator denominator")
    integer(value["config"]["tempo"], 1_000_000, 960_000_000)
    integer(value["config"]["numerator"], 1, 32)
    require(value["config"]["denominator"] in [1, 2, 4, 8, 16, 32], "unsupported meter")
    require(type(value["tracks"]) is dict and 1 <= len(value["tracks"]) <= 16, "1..16 tracks required")
    require(type(value["order"]) is list and len(set(value["order"])) == len(value["order"]) and set(value["order"]) == set(value["tracks"]), "track order mismatch")
    seen = set()
    total_items = total_notes = 0
    for k, t in value["tracks"].items():
        track(t); require(k == t["id"], "track key mismatch")
        for it in t["items"].values():
            total_items += 1
            total_notes += len(it["notes"])
            for id_ in (it["id"], it["take"]):
                require(id_ not in seen, "identity collision")
                seen.add(id_)
    require(total_items <= 128 and total_notes <= 4096, "project exceeds 128 items / 4096 notes")
    require(len(dumps(value).encode()) < LIMIT // 2, "project too large for v0.1")
    return value
