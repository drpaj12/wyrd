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
# The PDF tutorial is copied to the site root (https://drpaj12.github.io/wyrd/wyrd-tutorial.pdf).
html_extra_path = ["../tutorial/wyrd-tutorial.pdf"]

# Shared Yggdrasil III look: the "Manuals" block (hub link on top, links to every manual) leads
# the sidebar on every page. Keep _templates/manuals.html identical across the four manuals.
templates_path = ["_templates"]
html_sidebars = {
    "**": ["manuals.html", "about.html", "navigation.html", "relations.html", "searchbox.html"],
}
