"""Sphinx configuration of the Wyrd III user manual.

Build: ``sphinx-build -W -b html docs/user build/docs`` (CI job ``docs``). Every command, flag and
TOML key in the pages was checked against wyrd/cli.py, wyrd/project.py, wyrd/settings.py and the
specs under docs/specs. The pages need no Wyrd or Odin III install to build.
"""

project = "Wyrd III"
author = "Wyrd III contributors"
copyright = "Wyrd III contributors"

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build"]
myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3
html_theme = "alabaster"
