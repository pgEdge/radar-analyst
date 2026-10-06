"""Hatchling build hook: sync web/dist into src/radar_analyst/webdist.

Runs before the wheel is assembled. If the Astro build output is
present we mirror it into the package tree and register the wheel
force-include, so the `webdist/` path referenced by
radar_analyst.server.static exists in the installed wheel. With no
Astro output the include is left unregistered and the wheel is
API-only.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class AstroBundleHook(BuildHookInterface):  # type: ignore[misc]
    PLUGIN_NAME = "custom"

    def initialize(
        self, version: str, build_data: dict[str, Any]
    ) -> None:
        root = Path(self.root)
        web_dist = root / "web" / "dist"
        target = root / "src" / "radar_analyst" / "webdist"

        if target.exists():
            shutil.rmtree(target)

        if web_dist.is_dir():
            shutil.copytree(web_dist, target)
            build_data.setdefault("force_include", {})[
                str(target)
            ] = "radar_analyst/webdist"
            self.app.display_info(
                f"Bundled Astro build from {web_dist} to "
                f"{target}"
            )
        else:
            # Leave webdist absent and unreferenced: the server
            # gracefully falls back to API-only mode.
            self.app.display_info(
                "web/dist not found; wheel will ship without "
                "the GUI (API-only mode)"
            )
