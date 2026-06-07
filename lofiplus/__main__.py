"""lofiplus CLI entry point."""

from __future__ import annotations

import argparse
import sys

from lofiplus import __repo__, __version__


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lofiplus",
        description="Interactive Lo-Fi music TUI with real-time spectrum analyzer",
        epilog=f"Repository: {__repo__}",
    )
    p.add_argument(
        "-v", "--version",
        action="version",
        version=f"lofiplus {__version__}",
    )
    p.add_argument(
        "-a", "--update",
        action="store_true",
        help="Pull latest version from GitHub before starting",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Check for a newer release and exit",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    if args.check:
        from lofiplus.core.updater import check_update
        check_update(print_only=True)
        sys.exit(0)

    if args.update:
        from lofiplus.core.updater import perform_update
        perform_update()
        # Fall through and start the app with the (possibly) updated code

    from lofiplus.app import LofiPlusApp
    LofiPlusApp().run()


if __name__ == "__main__":
    main()
