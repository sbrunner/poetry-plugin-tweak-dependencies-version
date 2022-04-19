import functools
from pathlib import Path
from typing import Mapping, Optional

import tomlkit
from poetry import factory as factory_mod
from poetry.core.packages.dependency import Dependency
from poetry.core.semver.version import Version
from poetry.core.semver.version_range import VersionRange


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


def _get_pyproject_path(start: Path = None) -> Optional[Path]:
    return _find_higher_file("pyproject.toml", start=start)


def get_config(start: Path = None) -> Mapping:
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

        for index in range(len(instance.package.requires)):
            require = instance.package.requires[index]
            name = require.name
            version_type = config.get(name, versions_type)

            new_range = require.constraint
            if version_type == "major":
                new_range = VersionRange(
                    Version(new_range.min.major, 0, 0),
                    new_range.max.next_major,
                    include_min=True,
                )
            if version_type == "minor":
                new_range = VersionRange(
                    Version(new_range.min.major, new_range.min.minor, 0),
                    new_range.max.next_minor,
                    include_min=True,
                )
            if version_type == "patch":
                new_range = VersionRange(
                    Version(
                        new_range.min.major, new_range.min.minor, new_range.min.patch
                    ),
                    new_range.max.next_patch,
                    include_min=True,
                )

            instance.package.requires[index] = Dependency(name, new_range)

        return instance

    getattr(factory_mod, "Factory").create_poetry = alt_poetry_create


def activate() -> None:
    _patch_poetry_create(factory_mod)
