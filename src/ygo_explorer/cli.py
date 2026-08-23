"""Command line entry points. The only place a refresh can be triggered offline."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .catalogue.dump import fetch_dump, load_meta
from .config import CACHE_DIR, CATALOGUE_LANGUAGES, collection_csv_path
from .database import open_database

__all__ = ["main"]


def _refresh_dump(args: argparse.Namespace) -> int:
    before = load_meta()
    if before is not None and not args.force:
        print(
            f"Cached dump is {before.age_days:.1f} days old "
            f"({before.card_count} cards). Pass --force to refetch."
        )
        return 0

    languages = ", ".join(CATALOGUE_LANGUAGES) or "none"
    print(
        f"Fetching the YGOPRODeck bulk dump, plus name indexes for {languages} "
        f"({1 + len(CATALOGUE_LANGUAGES)} requests, tens of MB)..."
    )
    meta = asyncio.run(fetch_dump(force=args.force, cache_dir=CACHE_DIR))
    print(
        f"Cached {meta.card_count} cards ({meta.byte_size / 1_048_576:.1f} MB) "
        f"at {meta.fetched_at}"
    )
    if meta.languages:
        print(f"Also searchable in: {', '.join(meta.languages)}")
    elif CATALOGUE_LANGUAGES:
        print("No localized names were available; search falls back to English.")
    return 0


def _status(args: argparse.Namespace) -> int:
    csv_path = collection_csv_path()
    con = open_database(csv_path)
    try:
        total, distinct = con.execute(
            "SELECT SUM(quantity), COUNT(DISTINCT passcode) FROM collection"
        ).fetchone()
        rows, matched, unmatched, unmatched_passcodes = con.execute(
            "SELECT collection_rows, matched_rows, unmatched_rows, unmatched_passcodes "
            "FROM catalogue_status"
        ).fetchone()
    finally:
        con.close()

    meta = load_meta()
    print(f"Export:          {csv_path}")
    print(f"Total copies:    {total}")
    print(f"Distinct cards:  {distinct}")
    print(f"Ledger rows:     {rows} ({matched} matched, {unmatched} unmatched)")
    if unmatched:
        print(f"                 {unmatched_passcodes} passcode(s) not in the dump")
    if meta is None:
        print("Catalogue:       not fetched — run 'ygo-explorer refresh-dump'")
    else:
        print(
            f"Catalogue:       {meta.card_count} cards, "
            f"fetched {meta.age_days:.1f} days ago"
        )
        searchable = ", ".join(["EN", *meta.languages])
        print(f"Searchable in:   {searchable}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ygo-explorer", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser(
        "refresh-dump", help="download and cache the YGOPRODeck bulk card dump"
    )
    refresh.add_argument(
        "--force", action="store_true", help="refetch even if a cache already exists"
    )
    refresh.set_defaults(handler=_refresh_dump)

    status = sub.add_parser("status", help="summarize the collection and the catalogue")
    status.set_defaults(handler=_status)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
