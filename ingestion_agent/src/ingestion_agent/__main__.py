"""CLI entry point for the RazTech Ingestion Agent."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional, Sequence

from ingestion_agent.pipeline import create_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="ingestion-agent",
        description="RazTech AI Content Pipeline — Ingestion Agent",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="Path to YAML configuration override",
        default=None,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watch", help="Monitor watch directories continuously")
    watch.add_argument(
        "--once",
        action="store_true",
        help="Scan once and process current candidates, then exit",
    )

    process = sub.add_parser("process", help="Process a single recording file")
    process.add_argument("path", type=Path, help="Path to the recording")
    process.add_argument(
        "--skip-stability",
        action="store_true",
        help="Skip the file-size stability wait",
    )
    process.add_argument(
        "--copy",
        action="store_true",
        help="Copy instead of move into the content store",
    )
    process.add_argument(
        "--keep-on-failure",
        action="store_true",
        help="Do not move the source into /failed on validation errors",
    )
    return parser


async def _async_main(argv: Optional[Sequence[str]] = None) -> int:
    """Async CLI implementation.

    Args:
        argv: Optional argument vector (excluding program name).

    Returns:
        Process exit code (0 success, 1 failure).
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    pipeline = create_pipeline(args.config)

    if args.command == "process":
        result = await pipeline.process_file(
            args.path,
            skip_stability=args.skip_stability,
            copy=args.copy,
            move_on_failure=not args.keep_on_failure,
        )
        print(result.format_output())
        return 0 if result.success else 1

    if args.command == "watch":
        if args.once:
            watcher_files = []
            from ingestion_agent.watcher import RecordingWatcher

            async def collect(path: Path) -> None:
                watcher_files.append(path)

            # Use scan_once via a temporary watcher, then process.
            temp = RecordingWatcher(pipeline.config, on_detected=collect)
            candidates = temp.scan_once()
            exit_code = 0
            for item in candidates:
                result = await pipeline.process_file(item.path)
                print(result.format_output())
                if not result.success:
                    exit_code = 1
            if not candidates:
                print("No candidate recordings found.", file=sys.stderr)
            return exit_code

        await pipeline.watch_forever()
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Console-script entry point.

    Args:
        argv: Optional argument vector.
    """
    try:
        raise SystemExit(asyncio.run(_async_main(argv)))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
