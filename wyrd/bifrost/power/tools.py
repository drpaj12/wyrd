"""Where the external tools are; nothing is installed, a missing one is reported."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PowerTools:
    odin3: Path
    vtr_root: Path
    openroad: Path | None
    pdk: Path | None
    heavy_run: Path | None

    def vpr(self) -> Path:
        return self.vtr_root / "build/vpr/vpr"

    def ace(self) -> Path:
        return self.vtr_root / "build/ace2/ace"

    def arch(self) -> Path:
        return self.vtr_root / "vtr_flow/arch/timing/k6_frac_N10_frac_chain_mem32K_40nm.xml"

    def tech(self) -> Path:
        return self.vtr_root / "vtr_flow/tech/PTM_45nm/45nm.xml"

    def restore_latch(self) -> Path:
        return self.vtr_root / "vtr_flow/scripts/restore_multiclock_latch.pl"

    def liberty(self) -> Path | None:
        return (
            self.pdk / "libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
            if self.pdk
            else None
        )

    def verilog_models(self) -> Path | None:
        return self.pdk / "libs.ref/sky130_fd_sc_hd/verilog" if self.pdk else None

    def missing(self) -> list[str]:
        need: list[tuple[str, Path | None]] = [
            ("odin3", self.odin3),
            ("vpr", self.vpr()),
            ("ace", self.ace()),
            ("vpr arch", self.arch()),
            ("vpr tech file", self.tech()),
            ("openroad", self.openroad),
            ("sky130 liberty", self.liberty()),
        ]
        out = [n for n, p in need if p is None or not p.exists()]
        if shutil.which("iverilog") is None:
            out.append("iverilog")
        return out


def discover(ws: Path | None = None) -> PowerTools:
    """Tools of the odin3-ws layout; WYRD_ODIN3, VTR_ROOT, WYRD_OPENROAD, PDK_ROOT override."""
    root = ws or Path(os.environ.get("ODIN3_WS", Path.home() / "odin3-ws"))
    odin = Path(os.environ.get("WYRD_ODIN3", root / "odin3/build/rel-main3/odin3"))
    vtr = Path(os.environ.get("VTR_ROOT", root / "external/vtr-verilog-to-routing"))
    orp = Path(os.environ.get("WYRD_OPENROAD", root / "work/tools/mamba/envs/orcond/bin/openroad"))
    pdk = (
        Path(os.environ["PDK_ROOT"]) / "sky130A"
        if "PDK_ROOT" in os.environ
        else root / "work/tools/pdk/sky130A"
    )
    heavy = root / "odin3/tools/heavy-run"
    return PowerTools(
        odin,
        vtr,
        orp if orp.exists() else None,
        pdk if pdk.exists() else None,
        heavy if heavy.exists() else None,
    )
