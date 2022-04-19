import builtins
import functools
from pathlib import Path
from typing import Mapping, Optional

import tomlkit
from poetry import factory as factory_mod
from poetry.core import factory as core_factory_mod
from poetry.core.packages.dependency import Dependency
from poetry.core.semver.version import Version
from poetry.core.semver.version_range import VersionRange


class _State:
    def __init__(
        self,
        patched_poetry_create: bool = False,
        patched_core_poetry_create: bool = False,
        patched_poetry_command_run: bool = False,
        patched_poetry_command_shell: bool = False,
    ) -> None:
        self.patched_poetry_create = patched_poetry_create
        self.patched_core_poetry_create = patched_core_poetry_create
        self.patched_poetry_command_run = patched_poetry_command_run
        self.patched_poetry_command_shell = patched_poetry_command_shell
        self.original_import_func = builtins.__import__


_state = _State()


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
                    Version(new_range.min.major, new_range.min.minor, new_range.min.patch),
                    new_range.max.next_patch,
                    include_min=True,
                )

            instance.package.requires[index] = Dependency(name, new_range)

        return instance

    getattr(factory_mod, "Factory").create_poetry = alt_poetry_create


def _patch_poetry_command_run(run_mod) -> None:
    original_poetry_command_run = getattr(run_mod, "RunCommand").handle

    @functools.wraps(original_poetry_command_run)
    def alt_poetry_command_run(self, *args, **kwargs):
        # As of version 1.0.0b2, on Linux, the `poetry run` command
        # uses `os.execvp` function instead of spawning a new process.
        # This prevents the atexit `deactivate` hook to be invoked.
        # For this reason, we immediately call `deactivate` before
        # actually executing the run command.
        return original_poetry_command_run(self, *args, **kwargs)

    getattr(run_mod, "RunCommand").handle = alt_poetry_command_run


def _patch_poetry_command_shell(shell_mod) -> None:
    original_poetry_command_shell = getattr(shell_mod, "ShellCommand").handle

    @functools.wraps(original_poetry_command_shell)
    def alt_poetry_command_shell(self, *args, **kwargs):
        return original_poetry_command_shell(self, *args, **kwargs)

    getattr(shell_mod, "ShellCommand").handle = alt_poetry_command_shell


def activate() -> None:
    @functools.wraps(builtins.__import__)
    def alt_import(name, globals=None, locals=None, fromlist=(), level=0):
        module = _state.original_import_func(name, globals, locals, fromlist, level)

        if not _state.patched_poetry_create:
            try:
                if name == "poetry.factory" and fromlist:
                    _patch_poetry_create(module)
                    _state.patched_poetry_create = True
                elif name == "poetry" and "factory" in fromlist:
                    _patch_poetry_create(module.factory)
                    _state.patched_poetry_create = True
            except (ImportError, AttributeError):
                pass

        if not _state.patched_core_poetry_create:
            try:
                if name == "poetry.core.factory" and fromlist:
                    _patch_poetry_create(module)
                    _state.patched_core_poetry_create = True
                elif name == "poetry.core" and "factory" in fromlist:
                    _patch_poetry_create(module.factory)
                    _state.patched_core_poetry_create = True
            except (ImportError, AttributeError):
                pass

        if not _state.patched_poetry_command_run:
            try:
                if name == "poetry.console.commands.run" and fromlist:
                    _patch_poetry_command_run(module)
                    _state.patched_poetry_command_run = True
                elif name == "poetry.console.commands" and "run" in fromlist:
                    _patch_poetry_command_run(module.run)
                    _state.patched_poetry_command_run = True
            except (ImportError, AttributeError):
                pass

        if not _state.patched_poetry_command_shell:
            try:
                if name == "poetry.console.commands.shell" and fromlist:
                    _patch_poetry_command_shell(module)
                    _state.patched_poetry_command_shell = True
                elif name == "poetry.console.commands" and "shell" in fromlist:
                    _patch_poetry_command_shell(module.shell)
                    _state.patched_poetry_command_shell = True
            except (ImportError, AttributeError):
                pass

        return module

    builtins.__import__ = alt_import
