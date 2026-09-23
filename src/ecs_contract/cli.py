"""ecsc: the command line for the ECS config contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ecs_contract import __version__
from ecs_contract.contract import ContractFileError, check, load
from ecs_contract.problems import Problem
from ecs_contract.reserved import is_secret_shaped

if TYPE_CHECKING:
    from ecs_contract.render import Live

OK, REFUSED, MISUSE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecsc", description="Who owns what in an ECS task definition."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    contract = argparse.ArgumentParser(add_help=False)
    contract.add_argument("--parameters", required=True, metavar="PATH")
    contract.add_argument("--secrets", required=True, metavar="PATH")
    contract.add_argument(
        "--reserved",
        action="append",
        default=[],
        metavar="NAME",
        help="extra name the deploy workflow sets itself, repeatable",
    )
    contract.add_argument(
        "--allow-secret-shaped",
        action="append",
        default=[],
        metavar="NAME",
        help="parameter whose name looks like a secret but is not one, repeatable",
    )
    output = argparse.ArgumentParser(add_help=False)
    output.add_argument(
        "--format",
        choices=("auto", "text", "github"),
        default="auto",
        help="github prints workflow annotations; auto picks github inside GitHub Actions",
    )
    one_environment = argparse.ArgumentParser(add_help=False)
    one_environment.add_argument("--environment", "-e", required=True, metavar="NAME")
    service = argparse.ArgumentParser(add_help=False)
    service.add_argument("--cluster", required=True)
    service.add_argument("--service", required=True)
    service.add_argument("--container", help="container to render; required when there are several")
    service.add_argument("--region", default=os.environ.get("AWS_REGION"))
    config = argparse.ArgumentParser(add_help=False)
    config.add_argument(
        "--config-secret",
        metavar="NAME_OR_ARN",
        help="the service's own config secret, which vault-sourced keys are bound out of",
    )
    image = argparse.ArgumentParser(add_help=False)
    group = image.add_mutually_exclusive_group()
    group.add_argument("--image", help="full image reference for the container")
    group.add_argument("--image-tag", help="replace only the tag of the live image")

    check_parser = commands.add_parser(
        "check",
        parents=[contract, output],
        help="check the parameters and secrets files, with no credentials and no network",
        description="Check the application side of the contract. Exit 0 when it holds, 1 when"
        " it does not, 2 when a file cannot be read.",
    )
    check_parser.add_argument(
        "--environment",
        "-e",
        action="append",
        metavar="NAME",
        help="environment to check, repeatable; default is every environment in either file",
    )

    render_parser = commands.add_parser(
        "render",
        parents=[contract, output, one_environment, service, config, image],
        help="render the next task definition from the live one; reads AWS",
        description="Read the revision the service runs now, replace environment, secrets and"
        " the image of one container, and write the registration input. Nothing else changes.",
    )
    target = render_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", metavar="PATH", help="where to write the task definition JSON")
    target.add_argument(
        "--dry-run", action="store_true", help="print what would change, by name, and write nothing"
    )

    commands.add_parser(
        "drift",
        parents=[contract, output, one_environment, service, config, image],
        help="compare what a deploy would write with what is live; reads AWS",
        description="Exit 0 when a deploy would change nothing, 1 when it would.",
    )

    guard_parser = commands.add_parser(
        "guard",
        parents=[output],
        help="refuse a rendered task definition that breaks a deploy guard",
    )
    guard_parser.add_argument("--task-definition", required=True, metavar="PATH")
    guard_parser.add_argument("--container")
    guard_parser.add_argument("--allow-secret-shaped", action="append", default=[], metavar="NAME")
    guard_parser.add_argument(
        "--expect-task-definition",
        metavar="ARN",
        help="the live revision render saw; refuse if the service moved since",
    )
    guard_parser.add_argument("--cluster")
    guard_parser.add_argument("--service")
    guard_parser.add_argument("--region", default=os.environ.get("AWS_REGION"))

    sync_parser = commands.add_parser(
        "sync",
        parents=[contract, output, one_environment],
        help="write vault-sourced values into the service's config secret; reads a vault and AWS",
    )
    sync_parser.add_argument("--config-secret", required=True, metavar="NAME_OR_ARN")
    sync_parser.add_argument("--vault-backend", required=True, choices=("1password", "hashicorp"))
    sync_parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    sync_parser.add_argument(
        "--prune",
        action="store_true",
        help="drop keys the contract no longer names; by default they are kept for rollbacks",
    )
    sync_parser.add_argument("--dry-run", action="store_true", help="report by name, write nothing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.format == "auto":
        args.format = "github" if os.environ.get("GITHUB_ACTIONS") == "true" else "text"
    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "check": _check,
        "render": _render,
        "drift": _drift,
        "guard": _guard,
        "sync": _sync,
    }
    try:
        return handlers[args.command](args)
    except ContractFileError as error:
        return _fail(str(error))
    except ImportError as error:
        return _fail(f"this command reads AWS; install ecs-contract[aws] ({error.name})")


def _fail(message: str) -> int:
    print(f"ecsc: {message}", file=sys.stderr)
    return MISUSE


def _emit(problems: Sequence[Problem], output: str, label: str = "problem") -> None:
    for problem in problems:
        print(problem.github() if output == "github" else problem.text())
    if problems:
        count = len(problems)
        print(f"ecsc: {count} {label}{'' if count == 1 else 's'}")


def _warn(problems: Sequence[Problem], output: str) -> None:
    for problem in problems:
        if output == "github":
            print(problem.github().replace("::error ", "::warning ", 1))
        else:
            print(f"warning: {problem.text()}")


def _check(args: argparse.Namespace) -> int:
    report = check(
        args.parameters,
        args.secrets,
        args.environment,
        reserved=args.reserved,
        allow_secret_shaped=args.allow_secret_shaped,
    )
    if report.problems:
        _emit(report.problems, args.format)
        return REFUSED
    for environment, counts in report.counts.items():
        print(f"{environment}: parameters={counts.parameters} secrets={counts.secrets}")
    return OK


@dataclass(frozen=True)
class _Prepared:
    task_definition: dict[str, Any]
    live: Live
    rendered: dict[str, Any]
    current: dict[str, Any]


def _prepare(args: argparse.Namespace) -> _Prepared | int:
    """Shared by render and drift: check the contract, resolve sources, render."""
    from ecs_contract.aws import AwsUnavailableError, clients  # noqa: PLC0415
    from ecs_contract.render import (  # noqa: PLC0415
        RenderError,
        live,
        outside_writers,
        pick_container,
        render,
        replace_tag,
    )
    from ecs_contract.sources import resolve  # noqa: PLC0415

    report = check(
        args.parameters,
        args.secrets,
        [args.environment],
        reserved=args.reserved,
        allow_secret_shaped=args.allow_secret_shaped,
    )
    if report.problems:
        _emit(report.problems, args.format)
        return REFUSED
    parameters = dict(load(args.parameters, "parameters").environments[args.environment])
    secrets = load(args.secrets, "secrets").environments[args.environment]
    try:
        aws = clients(args.region)
        resolution = resolve(args.secrets, args.environment, secrets, aws, args.config_secret)
        if resolution.problems:
            _warn(resolution.warnings, args.format)
            _emit(resolution.problems, args.format)
            return REFUSED
        _warn(resolution.warnings, args.format)
        current = live(aws, args.cluster, args.service)
        live_container = pick_container(current.task_definition, args.container)
        image = args.image or (
            replace_tag(str(live_container["image"]), args.image_tag) if args.image_tag else None
        )
        rendered = render(current, args.container, parameters, resolution.bindings, image)
    except AwsUnavailableError as error:
        return _fail(str(error))
    except RenderError as error:
        print(f"ecsc: {error}")
        return REFUSED
    _warn(
        [
            Problem(
                args.secrets,
                args.environment,
                "-",
                f"the container also reads {writer}; variables set there bypass the contract",
            )
            for writer in outside_writers(live_container)
        ],
        args.format,
    )
    return _Prepared(rendered, current, pick_container(rendered, args.container), live_container)


def _render(args: argparse.Namespace) -> int:
    from ecs_contract.drift import compare  # noqa: PLC0415
    from ecs_contract.github import set_output  # noqa: PLC0415

    prepared = _prepare(args)
    if isinstance(prepared, int):
        return prepared
    changes = compare(
        prepared.rendered,
        prepared.current,
        image=bool(args.image or args.image_tag),
    )
    print(f"live revision: {prepared.live.revision}")
    for change in changes:
        print(f"change: {change.text()}")
    if not changes:
        print("change: none; the next revision would match the live one")
    if args.dry_run:
        return OK
    Path(args.out).write_text(
        json.dumps(prepared.task_definition, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out}")
    set_output("task-definition", args.out)
    set_output("live-task-definition", prepared.live.task_definition_arn)
    set_output("changes", str(len(changes)))
    return OK


def _drift(args: argparse.Namespace) -> int:
    from ecs_contract.drift import compare  # noqa: PLC0415

    prepared = _prepare(args)
    if isinstance(prepared, int):
        return prepared
    differences = compare(
        prepared.rendered,
        prepared.current,
        image=bool(args.image or args.image_tag),
    )
    print(f"live revision: {prepared.live.revision}")
    for difference in differences:
        text = f"drift: {difference.text()}"
        print(f"::error title=ecs-contract drift::{text}" if args.format == "github" else text)
    if differences:
        count = len(differences)
        print(f"ecsc: {count} difference{'' if count == 1 else 's'}")
        return REFUSED
    print("drift: none")
    return OK


def _guard(args: argparse.Namespace) -> int:
    path = args.task_definition
    try:
        task_definition = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        return _fail(f"{path}: cannot read: {error.strerror or error}")
    except ValueError:
        return _fail(f"{path}: not JSON")
    from ecs_contract.render import RenderError, pick_container  # noqa: PLC0415

    try:
        container = pick_container(task_definition, args.container)
    except RenderError as error:
        print(f"ecsc: {error}")
        return REFUSED
    allowed = set(args.allow_secret_shaped)
    problems = [
        Problem(
            path,
            "-",
            str(entry.get("name")),
            "looks like a secret but sits in environment; bind it through secrets",
        )
        for entry in container.get("environment") or []
        if is_secret_shaped(str(entry.get("name", ""))) and entry.get("name") not in allowed
    ]
    if args.expect_task_definition:
        if not (args.cluster and args.service):
            return _fail("--expect-task-definition needs --cluster and --service")
        from ecs_contract.aws import AwsUnavailableError, clients  # noqa: PLC0415
        from ecs_contract.render import family_revision, live  # noqa: PLC0415

        try:
            current = live(clients(args.region), args.cluster, args.service)
        except AwsUnavailableError as error:
            return _fail(str(error))
        except RenderError as error:
            print(f"ecsc: {error}")
            return REFUSED
        if current.task_definition_arn != args.expect_task_definition:
            problems.append(
                Problem(
                    path,
                    "-",
                    "-",
                    f"the service moved from {family_revision(args.expect_task_definition)} to"
                    f" {current.revision} since render; render again",
                )
            )
    if problems:
        _emit(problems, args.format)
        return REFUSED
    print("guard: passed")
    return OK


def _sync(args: argparse.Namespace) -> int:
    from ecs_contract.aws import AwsUnavailableError, clients  # noqa: PLC0415
    from ecs_contract.github import mask  # noqa: PLC0415
    from ecs_contract.sources import config_secret_arn  # noqa: PLC0415
    from ecs_contract.sync import SyncError, sync  # noqa: PLC0415
    from ecs_contract.vaults import VaultError, backend  # noqa: PLC0415

    report = check(
        args.parameters,
        args.secrets,
        [args.environment],
        reserved=args.reserved,
        allow_secret_shaped=args.allow_secret_shaped,
    )
    if report.problems:
        _emit(report.problems, args.format)
        return REFUSED
    secrets = load(args.secrets, "secrets").environments[args.environment]
    references = {key: str(s["vault"]) for key, s in secrets.items() if "vault" in s}
    if not references:
        print("sync: no vault-sourced keys; nothing to write")
        return OK
    try:
        store = backend(args.vault_backend)
    except VaultError as error:
        return _fail(str(error))
    values: dict[str, str] = {}
    problems: list[Problem] = []
    for key, reference in sorted(references.items()):
        try:
            value = store.read(reference)
        except VaultError as error:
            problems.append(Problem(args.secrets, args.environment, key, str(error)))
            continue
        mask(value)
        values[key] = value
    if problems:
        _emit(problems, args.format)
        return REFUSED
    try:
        aws = clients(args.region)
        arn = config_secret_arn(aws, args.config_secret)
        if arn is None:
            print(f"ecsc: config secret {args.config_secret} not found")
            return REFUSED
        result = sync(aws, arn, values, prune=args.prune, dry_run=args.dry_run)
    except AwsUnavailableError as error:
        return _fail(str(error))
    except SyncError as error:
        print(f"ecsc: {error}")
        return REFUSED
    for label, keys in (
        ("added", result.added),
        ("updated", result.updated),
        ("unchanged", result.unchanged),
        ("kept", result.kept),
        ("removed", result.removed),
    ):
        for key in keys:
            print(f"sync: {key}: {label}")
    if args.dry_run:
        print("sync: dry run, nothing written")
    else:
        print("sync: written" if result.written else "sync: already current, nothing written")
    return OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
