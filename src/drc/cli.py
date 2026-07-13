from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from .analysis import analyze
from .audit import audit_model_cohort, audit_retrospective
from .config import load_config
from .export import export
from .runner import plan_summary, rescore, run, should_stop
from .store import Store


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _status(config_path: str) -> tuple[dict[str, object], str | None, dict[str, object]]:
    config = load_config(config_path)
    with Store(config.database) as store:
        status = store.status(config.name, config.model.record_id)
        routes = {
            "main": store.route_status(config.name, config.model.record_id),
            "before": store.route_status(config.sentinels.before_stage, config.model.record_id),
            "after": store.route_status(config.sentinels.after_stage, config.model.record_id),
        }
    ready = (
        routes["main"]["mismatches"] == 0
        and routes["main"]["unpinned"] == 0
        and routes["before"]["calls"] >= config.sentinels.calls_each
        and routes["after"]["calls"] >= config.sentinels.calls_each
        and routes["before"]["mismatches"] == 0
        and routes["after"]["mismatches"] == 0
    )
    return status.as_dict(), should_stop(status, config), {"routes": routes, "ready": ready}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="drc", description="MiniMax confidence study")
    root.add_argument("--config", default="configs/study.toml")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="show the frozen design without generating tasks")
    commands.add_parser("status", help="show labels, spend, and stopping state")
    collection = commands.add_parser("run", help="resume collection under hard caps")
    collection.add_argument(
        "--stream-telemetry",
        action="store_true",
        help="use SSE and retain chunk timing; provider pin and fallback policy are unchanged",
    )
    commands.add_parser("rescore", help="reapply the mechanical parser and verifier")

    analysis = commands.add_parser("analyze", help="perform the registered one-look analysis")
    analysis.add_argument("--frozen", default="analysis/confidence-minimax-frozen.json")
    analysis.add_argument("--out", default="analysis/confidence-minimax-prospective.json")
    analysis.add_argument("--predictions", default="analysis/confidence-minimax-prospective-predictions.jsonl")
    analysis.add_argument("--bootstrap", type=int, default=2000)

    release = commands.add_parser("export", help="write public compact and trace artifacts")
    release.add_argument("--out", default="data/exports/prospective-v1")

    commands.add_parser("next", help="print the next protocol-authorized action")
    commands.add_parser("audit", help="recompute released metrics and checksums")
    model_audit = commands.add_parser("audit-model", help="check whether existing model calls support replication")
    model_audit.add_argument("--database", default="data/exports/drc.sqlite.gz")
    model_audit.add_argument("--model", required=True)
    model_audit.add_argument("--out")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = load_config(args.config)

    if args.command == "plan":
        print(json.dumps(plan_summary(config), indent=2))
        return 0
    if args.command == "status":
        status, reason, protocol = _status(args.config)
        print(json.dumps({"study": config.name, "status": status, "stop_reason": reason, "protocol": protocol}, indent=2))
        return 0
    if args.command == "run":
        if config.collection_locked:
            raise SystemExit(
                "collection is locked for this registered study; finish v1 with its original collector"
            )
        print(
            json.dumps(
                asyncio.run(run(config, stream_telemetry=args.stream_telemetry)),
                indent=2,
            )
        )
        return 0
    if args.command == "rescore":
        print(json.dumps(rescore(config), indent=2))
        return 0
    if args.command == "analyze":
        output = Path(args.out)
        if output.exists():
            raise SystemExit(f"one-look result already exists: {output}")
        status, reason, protocol = _status(args.config)
        if reason is None:
            raise SystemExit("prospective stopping condition has not been reached")
        if not protocol["ready"]:
            raise SystemExit("provider continuity or post-sentinel requirement is not satisfied")
        report, predictions = analyze(config, args.frozen, replicates=args.bootstrap)
        _write_json(output, report)
        prediction_path = Path(args.predictions)
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        prediction_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in predictions)
        )
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "export":
        print(json.dumps(export(config, args.out), indent=2))
        return 0
    if args.command == "next":
        status, reason, protocol = _status(args.config)
        result = Path("analysis/confidence-minimax-prospective.json")
        if reason is None:
            action = "Continue the frozen collection. Do not inspect efficacy metrics."
        elif not result.exists():
            action = "Freeze the database checksum, run `drc analyze` once, then publish the result."
        else:
            report = json.loads(result.read_text())
            action = (
                "Register and run the USD 10 streaming feasibility smoke."
                if report.get("gate", {}).get("pass")
                else "Report the negative result and stop; streaming remains unauthorized."
            )
        if reason is not None and not protocol["ready"]:
            action = "Run the frozen post-sentinel with the original collector, then snapshot the database."
        print(json.dumps({"status": status, "stop_reason": reason, "protocol": protocol, "next_action": action}, indent=2))
        return 0
    if args.command == "audit":
        result = audit_retrospective()
        print(json.dumps(result, indent=2))
        return 0 if result["pass"] else 1
    if args.command == "audit-model":
        result = audit_model_cohort(args.database, args.model)
        if args.out:
            _write_json(Path(args.out), result)
        print(json.dumps(result, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
