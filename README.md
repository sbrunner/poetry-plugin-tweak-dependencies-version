# Poetry plugin tweak dependencies version

Plugin use to tweak the dependencies of the project.

Will be used when we have different constraints for the dependencies, like publish and dependency upgrader like Renovate.

This plugin will let us tweak the dependencies of the published packages.

Config:

```toml
[build-system]
requires = ["poetry-core>=1.0.0", "poetry-plugin-tweak-dependencies-version"]
build-backend = "poetry.core.masonry.api"

[tool.poetry-plugin-tweak-dependencies-version]
default = "(major|minor|patch|full)" # Default to full
"<package>" = "(major|minor|patch|full)"
```
