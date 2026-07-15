"""Select the smallest safe CI scope for a set of changed paths."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterable, Sequence

from scripts.fork_contract import FORK_CONTRACT_PATHS, FORK_ONLY_TEST_PATHS

AREA_NAMES = (
    "frontend",
    "backend",
    "helm",
    "docker",
    "migrations",
    "fork_contract",
    "single_host_lifecycle",
)
SINGLE_HOST_LIFECYCLE_PATHS = (
    "deploy/single-host/*.py",
    "deploy/single-host/docker-compose.yml",
    "deploy/single-host/fixtures/**",
    "tests/integration/test_single_host_docker_lifecycle.py",
)


@dataclass(frozen=True, slots=True)
class CiScope:
    frontend: bool = False
    backend: bool = False
    helm: bool = False
    docker: bool = False
    migrations: bool = False
    fork_contract: bool = False
    single_host_lifecycle: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def level(self) -> str:
        return "full" if all(getattr(self, area) for area in AREA_NAMES) else "fast"

    @property
    def enabled_areas(self) -> tuple[str, ...]:
        return tuple(area for area in AREA_NAMES if getattr(self, area))

    def github_outputs(self) -> dict[str, str]:
        outputs = {area: str(getattr(self, area)).lower() for area in AREA_NAMES}
        outputs["full_suite"] = str(self.level == "full").lower()
        outputs["level"] = self.level
        outputs["reasons"] = ", ".join(self.reasons) or "no expensive checks required"
        return outputs


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def _normalise_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({path.strip().removeprefix("./") for path in paths if path.strip()}))


def _full_suite_reasons(paths: Sequence[str]) -> tuple[str, ...]:
    reasons: list[str] = []

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    for path in paths:
        if _matches(path, ("UPSTREAM_BASE",)):
            add("upstream synchronization")
        if _matches(path, ("pyproject.toml", "uv.lock", "frontend/package.json", "frontend/bun.lock")):
            add("dependencies")
        if _matches(path, ("app/db/alembic/**",)):
            add("database migrations")
        if _matches(path, ("app/**", "config/**", "scripts/**")):
            add("runtime source")
        if _matches(path, ("frontend/src/**",)) and not _matches(path, ("*.test.*", "*.spec.*")):
            add("runtime source")
        if _matches(
            path,
            (
                "Dockerfile",
                "Dockerfile.*",
                ".dockerignore",
                "docker-compose*.yml",
                "docker-compose*.yaml",
            ),
        ):
            add("container runtime")
        if _matches(path, ("Makefile", ".github/workflows/**")):
            add("shared CI contract")
    return tuple(reasons)


def classify_paths(paths: Iterable[str], *, force_full: bool = False, upstream_sync: bool = False) -> CiScope:
    """Return the CI areas required by *paths* and explain full-suite promotion."""

    normalised = _normalise_paths(paths)
    if force_full:
        return CiScope(**{area: True for area in AREA_NAMES}, reasons=("explicit full-suite request",))
    if upstream_sync:
        return CiScope(**{area: True for area in AREA_NAMES}, reasons=("upstream synchronization",))

    full_reasons = _full_suite_reasons(normalised)
    if full_reasons:
        return CiScope(**{area: True for area in AREA_NAMES}, reasons=full_reasons)

    frontend = any(_matches(path, ("frontend/**",)) for path in normalised)
    backend = any(
        _matches(path, (".github/scripts/**", "tests/**")) and not _matches(path, FORK_ONLY_TEST_PATHS)
        for path in normalised
    )
    helm = any(_matches(path, ("deploy/helm/**",)) for path in normalised)
    migrations = any(_matches(path, ("app/db/alembic/**",)) for path in normalised)
    fork_contract = any(_matches(path, FORK_CONTRACT_PATHS) for path in normalised)
    single_host_lifecycle = any(_matches(path, SINGLE_HOST_LIFECYCLE_PATHS) for path in normalised)
    reasons = (
        ("single-host deployment",) if any(_matches(path, ("deploy/single-host/**",)) for path in normalised) else ()
    )
    return CiScope(
        frontend=frontend,
        backend=backend,
        helm=helm,
        migrations=migrations,
        fork_contract=fork_contract,
        single_host_lifecycle=single_host_lifecycle,
        reasons=reasons,
    )


def changed_paths(base: str, head: str) -> tuple[str, ...]:
    """Read changed paths from Git, including the first-push fallback."""

    if not head:
        raise ValueError("head SHA is required")

    effective_base = base
    if not base or set(base) == {"0"}:
        parent = subprocess.run(
            ["git", "rev-parse", "--verify", f"{head}^"],
            check=False,
            capture_output=True,
            text=True,
        )
        if parent.returncode != 0:
            tree = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", head],
                check=True,
                capture_output=True,
                text=True,
            )
            return _normalise_paths(tree.stdout.splitlines())
        effective_base = parent.stdout.strip()

    diff = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACDMR", effective_base, head],
        check=True,
        capture_output=True,
        text=True,
    )
    return _normalise_paths(diff.stdout.splitlines())


def upstream_history_changed(head: str, upstream_ref: str, upstream_base_path: Path) -> bool:
    """Return whether *head* contains upstream commits newer than the recorded base."""

    recorded_base = upstream_base_path.read_text(encoding="utf-8").strip()
    merge_base = subprocess.run(
        ["git", "merge-base", head, upstream_ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return merge_base != recorded_base


def _parse_bool(value: str) -> bool:
    normalised = value.strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"", "0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean: {value}")


def _write_github_outputs(path: Path, scope: CiScope) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, value in scope.github_outputs().items():
            output.write(f"{name}={value}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base Git SHA")
    parser.add_argument("--head", required=True, help="head Git SHA")
    parser.add_argument("--force-full", type=_parse_bool, default=False)
    parser.add_argument("--upstream-ref")
    parser.add_argument("--upstream-base", type=Path, default=Path("UPSTREAM_BASE"))
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)

    paths = changed_paths(args.base, args.head)
    upstream_sync = False
    if args.upstream_ref:
        upstream_sync = upstream_history_changed(args.head, args.upstream_ref, args.upstream_base)
    scope = classify_paths(paths, force_full=args.force_full, upstream_sync=upstream_sync)
    if args.github_output is not None:
        _write_github_outputs(args.github_output, scope)

    print(
        json.dumps(
            {
                "base": args.base,
                "head": args.head,
                "paths": paths,
                "level": scope.level,
                "areas": scope.enabled_areas,
                "reasons": scope.reasons,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
