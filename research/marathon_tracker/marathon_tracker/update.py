from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG, DEFAULT_DOCS_DIR, load_races
from .extract import extract_dates
from .fetch import fetch_text
from .render import write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update marathon race date research outputs.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to race config JSON.")
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS_DIR, help="Static output directory.")
    parser.add_argument("--no-network", action="store_true", help="Render configured races without fetching pages.")
    parser.add_argument("--limit", type=int, default=0, help="Limit races for testing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    races = load_races(args.config)
    if args.limit:
        races = races[: args.limit]

    results = []
    for race in races:
        page_text = None
        if not args.no_network:
            urls = [url for url in [race.registration_url, race.official_url] if url]
            for url in dict.fromkeys(urls):
                try:
                    page_text = fetch_text(url)
                    break
                except RuntimeError as exc:
                    print(f"warning: {exc}", file=sys.stderr)
        results.append(extract_dates(race, page_text))

    write_outputs(results, args.docs_dir)
    print(f"wrote {len(results)} races to {args.docs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
