"""Poetry plugin use to tweak the dependencies of the project."""

import re
from typing import Any, Dict, Optional

import cleo.commands.command
import cleo.events.console_events
import cleo.io.io
from cleo.events.console_command_event import ConsoleCommandEvent
from cleo.events.event import Event
from cleo.events.event_dispatcher import EventDispatcher
from poetry.console.application import Application
from poetry.core.constraints.version import (
    Version,
    VersionConstraint,
    VersionRange,
    VersionRangeConstraint,
    parse_constraint,
)
from poetry.core.version.pep440 import Release
from poetry.plugins.application_plugin import ApplicationPlugin

_VERSION_RE = re.compile(r"^([1-9])+(\.([1-9])+(\.([1-9])+)?)?(.*)$")


class Plugin(ApplicationPlugin):
    """Poetry plugin use to tweak the dependencies of the project."""

    _application: Application
    _pyproject: Dict[str, Any]
    _plugin_config: Dict[str, Any]
    _state: Dict[str, Dict[str, VersionConstraint]]

    def activate(self, application: Application) -> None:
        """Activate the plugin."""
        self._application = application
        self._pyproject = self._application.poetry.pyproject.data
        self._plugin_config = self._pyproject.get("tool", {}).get(
            "poetry-plugin-tweak-dependencies-version", {}
        )
        for key, value in list(self._plugin_config.items()):
            if "_" in key:
                new_key = key.replace("_", "-")
                if new_key not in self._plugin_config:
                    self._plugin_config[new_key] = value
        self._state = {}

        event_dispatcher = application.event_dispatcher
        assert event_dispatcher is not None
        event_dispatcher.add_listener(cleo.events.console_events.COMMAND, self._apply_version)
        event_dispatcher.add_listener(cleo.events.console_events.SIGNAL, self._revert_version)
        event_dispatcher.add_listener(cleo.events.console_events.TERMINATE, self._revert_version)
        event_dispatcher.add_listener(cleo.events.console_events.ERROR, self._revert_version)

    def _revert_version(self, event: Event, kind: str, dispatcher: EventDispatcher):
        del event, kind, dispatcher

        for group_name, packages in self._state.items():
            dependencies = self._application.poetry.package.dependency_group(group_name).dependencies
            for dependency in dependencies:
                if dependency.name in packages:
                    dependency.constraint = packages[dependency.name]

    def _zero(self, version_pice: Optional[int]):
        return None if version_pice is None else 0

    def _min(self, constraint, release_new):
        return Version.parse(release_new.text) if (release_new < constraint.min.release) else constraint.min

    def _apply_version(self, event: Event, kind: str, dispatcher: EventDispatcher):
        del kind, dispatcher
        assert isinstance(event, ConsoleCommandEvent)

        if event.command.name not in ("build",):
            return

        default_version_type = self._plugin_config.get("default", "full")
        for group_name in self._application.poetry.package.dependency_group_names():
            dependencies = self._application.poetry.package.dependency_group(group_name).dependencies
            for index in range(len(dependencies)):  # pylint: disable=consider-using-enumerate
                require = dependencies[index]
                package_name = require.name
                package_version_type = self._plugin_config.get(package_name, default_version_type)

                constraint = require.constraint
                self._state.setdefault(group_name, {})[package_name] = constraint

                # print(constraint.min.minor,constraint.max.minor)
                if package_version_type == "present":
                    constraint = VersionRange()
                elif package_version_type == "major":
                    assert isinstance(constraint, VersionRangeConstraint)
                    assert constraint.min is not None
                    assert constraint.max is not None
                    constraint = VersionRange(
                        self._min(
                            constraint,
                            Release(
                                constraint.min.major,
                                self._zero(constraint.min.minor),
                                self._zero(constraint.min.patch),
                            ),
                        ),
                        constraint.max.next_major().next_major()
                        if constraint.max.is_unstable()
                        else constraint.max.next_major(),
                        include_min=True,
                    )
                elif package_version_type == "minor":
                    assert isinstance(constraint, VersionRangeConstraint)
                    assert constraint.min is not None
                    assert constraint.max is not None
                    constraint = VersionRange(
                        self._min(
                            constraint,
                            Release(
                                constraint.min.major,
                                constraint.min.minor,
                                self._zero(constraint.min.patch),
                            ),
                        ),
                        constraint.max.next_minor().next_minor()
                        if constraint.max.is_unstable()
                        else constraint.max.next_minor(),
                        include_min=True,
                    )
                elif package_version_type == "patch":
                    assert isinstance(constraint, VersionRangeConstraint)
                    assert constraint.min is not None
                    assert constraint.max is not None
                    constraint = VersionRange(
                        self._min(
                            constraint,
                            Release(constraint.min.major, constraint.min.minor, constraint.min.patch),
                        ),
                        constraint.max.next_patch().next_patch()
                        if constraint.max.is_unstable()
                        else constraint.max.next_patch(),
                        include_min=True,
                    )
                elif package_version_type == "full":
                    pass
                elif package_version_type is not None:
                    old_constraint = constraint
                    constraint = parse_constraint(package_version_type)
                    if not constraint.allows_all(old_constraint):
                        print(
                            f"WARNING: the original constraint '{old_constraint}' don't looks to be "
                            f"compatible with the new one '{package_version_type}'."
                        )

                if str(require.constraint) != str(constraint):
                    print(f"{package_name}: {require.constraint} => {constraint}.")
                require.constraint = constraint

    def _apply_version_on(self, dependencies):
        versions_type = self._plugin_config.get("default", "full")

        for package_name, full_version in dependencies.items():
            version = full_version["version"] if isinstance(full_version, dict) else full_version
            if version.startswith("=="):
                version = version[2:]

            version_match = _VERSION_RE.match(version)
            if version_match is None:
                continue

            package_version_type = self._plugin_config.get(package_name, versions_type)

            if package_version_type == "present":
                version = "*"
            elif package_version_type == "major":
                if version_match.group(2) is None and version_match.group(5) is None:
                    version = version_match.group(0)
                else:
                    version = f"{version_match.group(0)}.*"
            elif package_version_type == "minor":
                if version_match.group(4) is None and version_match.group(5) is None:
                    version = f"{version_match.group(0)}.{version_match.group(2)}"
                else:
                    version = f"{version_match.group(0)}.{version_match.group(2)}.*"
            elif package_version_type == "patch":
                if version_match.group(5) is not None:
                    version = f"{version_match.group(0)}.{version_match.group(2)}.{version_match.group(4)}"
            elif package_version_type == "full":
                pass
            elif package_version_type is not None:
                version = package_version_type

            if isinstance(full_version, dict):
                full_version["version"] = version
            else:
                dependencies[package_name] = version
