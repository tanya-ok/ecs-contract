"""ecsc: the command line for the ECS config contract."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from ecs_contract import __version__
from ecs_contract.contract import ContractFileError, check


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecsc",
        description="Who owns what in an ECS task definition.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    check_parser = commands.add_parser(
        "check",
        help="check the parameters and secrets files, with no credentials and no network",
        description="Check the application side of the contract. Exit 0 when it holds, 1 when"
        " it does not, 2 when a file cannot be read.",
    )
    check_parser.add_argument("--parameters", required=True, metavar="PATH")
    check_parser.add_argument("--secrets", required=True, metavar="PATH")
    check_parser.add_argument(
        "--environment",
        "-e",
        action="append",
        metavar="NAME",
        help="environment to check, repeatable; default is every environment in either file",
    )
    check_parser.add_argument(
        "--reserved",
        action="append",
        default=[],
        metavar="NAME",
        help="extra name the deploy workflow sets itself, repeatable",
    )
    check_parser.add_argument(
        "--allow-secret-shaped",
        action="append",
        default=[],
        metavar="NAME",
        help="parameter whose name looks like a secret but is not one, repeatable",
    )
    check_parser.add_argument(
        "--format",
        choices=("auto", "text", "github"),
        default="auto",
        help="github prints workflow annotations; auto picks github inside GitHub Actions",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return _check(args)
    return 2  # pragma: no cover


def _check(args: argparse.Namespace) -> int:
    output = args.format
    if output == "auto":
        output = "github" if os.environ.get("GITHUB_ACTIONS") == "true" else "text"
    try:
        report = check(
            args.parameters,
            args.secrets,
            args.environment,
            reserved=args.reserved,
            allow_secret_shaped=args.allow_secret_shaped,
        )
    except ContractFileError as error:
        print(f"ecsc: {error}", file=sys.stderr)
        return 2

    for problem in report.problems:
        print(problem.github() if output == "github" else problem.text())
    if report.problems:
        count = len(report.problems)
        print(f"ecsc: {count} problem{'' if count == 1 else 's'}")
        return 1
    for environment, counts in report.counts.items():
        print(f"{environment}: parameters={counts.parameters} secrets={counts.secrets}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
