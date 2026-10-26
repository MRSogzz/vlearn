from __future__ import annotations

import argparse
import sys

from rich.console import Console

from app.context import AppContext

console = Console()


def _ctx(args) -> AppContext:
    return AppContext.from_config(args.config)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vlearn")
    p.add_argument("--config", default="config/default.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest")
    s.add_argument("url")
    s.add_argument("--platform", default="youtube")

    s = sub.add_parser("run")
    s.add_argument("video_id")
    s.add_argument("--profile", default="standard")

    s = sub.add_parser("report")
    s.add_argument("run_id")
    s.add_argument("--format", default="md")

    s = sub.add_parser("review")
    s.add_argument("run_id")
    s.add_argument("--ref", required=True)
    s.add_argument("--old", required=True)
    s.add_argument("--new", required=True)
    s.add_argument("--note", default="")

    s = sub.add_parser("cost")
    s.add_argument("--daily", action="store_true")

    s = sub.add_parser("videos")
    s.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("trend")
    s.add_argument("action", choices=["import", "run"])
    s.add_argument("--path")
    s.add_argument("--top", type=int, default=20)

    args = p.parse_args(argv)
    ctx = _ctx(args)

    if args.cmd == "ingest":
        from app.ingest.pipeline import ingest_url
        r = ingest_url(ctx, args.url, args.platform)
        console.print(r)
        return 0

    if args.cmd == "run":
        from app.orchestrator import Orchestrator
        r = Orchestrator(ctx).analyze(args.video_id, args.profile)
        console.print(r)
        return 0

    if args.cmd == "report":
        row = ctx.db.get_report(args.run_id)
        if not row:
            console.print(f"[red]report {args.run_id} not found[/red]")
            return 1
        console.print(row["report_md"], markup=False, highlight=False)
        return 0

    if args.cmd == "review":
        from app.render.corrections import re_render_with_corrections
        cid = ctx.db.insert_correction(args.run_id, args.ref, args.old, args.new, args.note)
        path = re_render_with_corrections(ctx, args.run_id)
        console.print({"correction_id": cid, "rendered": path})
        return 0

    if args.cmd == "cost":
        console.print(ctx.ledger.summary(daily=args.daily))
        return 0

    if args.cmd == "videos":
        console.print(ctx.db.list_videos(args.limit))
        return 0

    if args.cmd == "trend":
        if args.action == "import":
            path = args.path or ctx.config["trend"]["csv_path"]
            n = ctx.db.import_trend_csv(path)
            console.print({"imported": n, "path": path})
            return 0
        console.print(ctx.db.trend_top(args.top))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())