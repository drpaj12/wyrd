"""The project tree shown in the GUI: designs, recipes and archs (spec section 5)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from wyrd.model import Design
from wyrd.project import Project


@dataclass(frozen=True)
class TreeNode:
    kind: str
    label: str
    path: Path | None = None
    children: tuple[TreeNode, ...] = ()


def _design_label(design: Design) -> str:
    return f"{design.name} (top: {design.top})" if design.top else design.name


def _file_node(root: Path, path: Path) -> TreeNode:
    rel = Path(os.path.relpath(path, root)).as_posix()
    return TreeNode("file", rel, path)


def _design_node(root: Path, design: Design) -> TreeNode:
    files = tuple(_file_node(root, f) for f in design.files)
    return TreeNode("design", _design_label(design), None, files)


def project_tree(project: Project) -> tuple[TreeNode, ...]:
    """Three group nodes: ``Designs``, ``Recipes`` and ``Archs``."""
    designs = tuple(_design_node(project.root, d) for d in project.designs.values())
    recipes = tuple(
        TreeNode("recipe", r.name, None, tuple(TreeNode("step", s.use) for s in r.steps))
        for r in project.recipes.values()
    )
    archs = tuple(
        TreeNode("arch", a) for a in sorted({run.arch for run in project.runs} - {""})
    )
    return (
        TreeNode("group", "Designs", None, designs),
        TreeNode("group", "Recipes", None, recipes),
        TreeNode("group", "Archs", None, archs),
    )
