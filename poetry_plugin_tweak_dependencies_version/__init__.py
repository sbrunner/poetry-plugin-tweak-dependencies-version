"""Poetry plugin use to tweak the dependencies of the project."""

import functools
from pathlib import Path
from typing import Mapping, Optional

import tomlkit
from poetry.core import factory as core_factory_mod  # type: ignore
from poetry.core.packages.dependency import Dependency  # type: ignore
from poetry.core.semver.version import Version  # type: ignore
from poetry.core.semver.version_range import VersionRange  # type: ignore


def _find_higher_file(*names: str, start: Path = None) -> Optional[Path]:
    # Note: We need to make sure we get a pathlib object. Many tox poetry
    # helpers will pass us a string and not a pathlib object. See issue #40.
    if start is None:
        start = Path.cwd()
    elif not isinstance(start, Path):
        start = Path(start)
    for level in [start, *start.parents]:
        for name in names:
            if (level / name).is_file():
                return level / name
    return None


def _get_pyproject_path(start: Optional[Path] = None) -> Optional[Path]:
    return _find_higher_file("pyproject.toml", start=start)


def get_config(start: Optional[Path] = None) -> Mapping:
    """Get the configuration for the plugin."""
    pyproject_path = _get_pyproject_path(start)
    if pyproject_path is None:
        return {}
    pyproject = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    return pyproject.get("tool", {}).get("poetry-plugin-tweak-dependencies-version", {})


def _patch_poetry_create(factory_mod) -> None:
    original_poetry_create = getattr(factory_mod, "Factory").create_poetry

    @functools.wraps(original_poetry_create)
    def alt_poetry_create(cls, *args, **kwargs):
        instance = original_poetry_create(cls, *args, **kwargs)

        config = get_config(kwargs.get("cwd", args[0]))
        versions_type = config.get("default", "full")

        for index in range(len(instance.package.requires)):  # pylint: disable=consider-using-enumerate
            require = instance.package.requires[index]
            name = require.name
            version_type = config.get(name, versions_type)

            constraint = require.constraint
            if version_type == "present":
                constraint = "*"
            if version_type == "major":
                constraint = VersionRange(
                    Version(constraint.min.major, 0, 0),
                    constraint.max.next_major,
                    include_min=True,
                )
            if version_type == "minor":
                constraint = VersionRange(
                    Version(constraint.min.major, constraint.min.minor, 0),
                    constraint.max.next_minor,
                    include_min=True,
                )
            if version_type == "patch":
                constraint = VersionRange(
                    Version(constraint.min.major, constraint.min.minor, constraint.min.patch),
                    constraint.max.next_patch,
                    include_min=True,
                )

            instance.package.requires[index] = Dependency(name, constraint)

        return instance

    getattr(factory_mod, "Factory").create_poetry = alt_poetry_create


def activate() -> None:
    """Activate the plugin."""
    _patch_poetry_create(core_factory_mod)
