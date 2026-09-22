"""Who owns what in an ECS task definition."""

from importlib.metadata import PackageNotFoundError, version

from ecs_contract.contract import ContractFileError, Counts, Report, check, load
from ecs_contract.problems import Problem

try:
    __version__ = version("ecs-contract")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = ["ContractFileError", "Counts", "Problem", "Report", "__version__", "check", "load"]
