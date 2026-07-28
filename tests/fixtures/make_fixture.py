"""Regenerate ``collection_fixture.csv`` byte-for-byte as the scanner would emit it.

Run with ``uv run python tests/fixtures/make_fixture.py``. Kept as a script rather
than a test helper so the fixture stays a checked-in, hand-readable artifact that
the loader tests read from disk exactly as they would a real export.

Mirrors ``lib/data/export/collection_csv.dart`` in the scanner app: RFC 4180,
CRLF line endings, no BOM, quote-doubling, and the formula-injection guard.
"""

from __future__ import annotations

from pathlib import Path

HEADER = [
    "passcode",
    "name",
    "set_code",
    "set_name",
    "rarity",
    "condition",
    "edition",
    "language",
    "quantity",
    "notes",
    "created_at",
    "updated_at",
]

# (passcode, name, set_code, set_name, rarity, condition, edition, language,
#  quantity, notes, created_at, updated_at)
ROWS: list[tuple[str, ...]] = [
    # A leading-zero passcode. Parsed as an int it would become 4041, and would
    # then match the wrong card — or no card at all.
    ("00004041", "Mystical Elf", "LOB-EN004", "Legend of Blue Eyes White Dragon",
     "Super Rare", "MINT", "FIRST", "EN", "1", "",
     "2026-01-02T08:00:00.000Z", "2026-01-02T08:00:00.000Z"),
    # Logged without a printing: set_code/set_name/rarity are all ''.
    ("46986414", "Dark Magician", "", "", "", "NEAR_MINT", "UNLIMITED", "EN", "4",
     "", "2026-01-03T09:30:00.000Z", "2026-01-03T09:30:00.000Z"),
    # Same passcode as the row above, different condition and edition: this is
    # what makes SUM(quantity) and COUNT(DISTINCT passcode) diverge.
    ("46986414", "Dark Magician", "SDY-006", "Starter Deck: Yugi", "Ultra Rare",
     "POOR", "FIRST", "DE", "2", "creased corner",
     "2026-01-04T10:15:00.000Z", "2026-02-01T11:00:00.000Z"),
    # Diacritics: must be findable as "necrovalley".
    ("47355498", "Nécrovalley", "AST-EN049", "Ancient Sanctuary", "Rare",
     "EXCELLENT", "UNLIMITED", "FR", "3", "",
     "2026-01-05T12:00:00.000Z", "2026-01-05T12:00:00.000Z"),
    # A name the formula guard fired on, and notes it fired on too. Exactly one
    # apostrophe must come off each.
    ("00000001", "=Test Formula Card", "TST-EN001", "Test Set", "Common", "GOOD",
     "LIMITED", "IT", "1", "-30% off",
     "2026-01-06T13:45:00.000Z", "2026-01-06T13:45:00.000Z"),
    # Embedded comma and quotes: RFC 4180 quoting with doubled internal quotes.
    ("27204311", 'Nibiru, the "Primal" Being', "MP22-EN261",
     "2022 Tin of the Pharaoh's Gods", "Ultra Rare", "LIGHT_PLAYED", "UNLIMITED",
     "JP", "2", "", "2026-01-07T14:20:00.000Z", "2026-01-07T14:20:00.000Z"),
    # Seven digits, as the real export contains.
    ("8736823", "Virtual World Hime - Nyannyan", "MP21-EN223",
     "2021 Tin of Ancient Battles", "Prismatic Secret Rare", "PLAYED",
     "UNLIMITED", "EN", "5", "", "2026-01-08T15:05:00.000Z",
     "2026-01-08T15:05:00.000Z"),
    # Present in the ledger, absent from the catalogue dump: must still appear.
    ("99999999", "Unlisted Promo Card", "", "", "", "NEAR_MINT", "UNLIMITED",
     "KR", "1", "not in the dump", "2026-01-09T16:00:00.000Z",
     "2026-01-09T16:00:00.000Z"),
]

TRIGGERS = {"=", "+", "-", "@", "\t", "\r"}


def guard_formula(field: str) -> str:
    if field and field[0] in TRIGGERS:
        return "'" + field
    return field


def escape(field: str) -> str:
    guarded = guard_formula(field)
    if any(ch in guarded for ch in (",", '"', "\n", "\r")):
        return '"' + guarded.replace('"', '""') + '"'
    return guarded


def to_csv(rows: list[tuple[str, ...]]) -> str:
    out = [",".join(escape(c) for c in HEADER)]
    out += [",".join(escape(c) for c in row) for row in rows]
    return "".join(line + "\r\n" for line in out)


if __name__ == "__main__":
    target = Path(__file__).with_name("collection_fixture.csv")
    target.write_bytes(to_csv(ROWS).encode("utf-8"))
    print(f"wrote {target} ({target.stat().st_size} bytes, {len(ROWS)} rows)")
