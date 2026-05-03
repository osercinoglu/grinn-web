#!/usr/bin/env python3
"""Pre-flight inspection tool for i-gRINN job bundles.

Run this BEFORE uploading your bundle to i-gRINN to catch the common errors
that cause server-side preflight rejection or container-side validation
failures. Each check pinpoints a specific failure mode that has actually
happened to users in practice.

Quick start:

    python scripts/inspect_sim.py --bundle ./my_results_dir/

or, for an explicit bundle:

    python scripts/inspect_sim.py \\
        --structure system_dry.pdb \\
        --trajectory traj_dry.xtc \\
        --topology  topol_dry.top

Exit codes:
    0  — all checks passed (warnings are OK)
    1  — at least one error (the i-gRINN job would fail)
    2  — script-level usage error (missing dep, bad CLI args, etc.)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

# i-gRINN production limits. The script falls back to these when shared.config
# can't be imported (e.g. user runs the script standalone). Override via CLI.
DEFAULT_MAX_TRAJECTORY_MB = 100
DEFAULT_MAX_OTHER_MB = 10
DEFAULT_MAX_FRAMES = 200
DEFAULT_INITPAIRFILTER_CUTOFF_A = 12.0

# Standard residues — anything outside this set is treated as a candidate
# ligand or non-standard residue when scanning for the ligand-far-from-protein
# heuristic.
STD_AMINO_ACIDS = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY",
    "HIS", "HID", "HIE", "HIP",  # AMBER protonation states
    "HSD", "HSE", "HSP",          # CHARMM protonation states
    "CYX", "CYM",                 # AMBER cysteine variants (disulfide / deprotonated)
    "ASH", "GLH", "LYN",          # AMBER protonation states
    "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR",
    "TRP", "TYR", "VAL",
}
STD_WATERS_IONS = {
    "HOH", "WAT", "TIP", "TIP3", "TIP3P", "SOL", "T3P", "T4P",
    "NA", "CL", "K", "MG", "CA", "ZN", "FE", "MN", "CU", "BR", "I",
    "NA+", "CL-", "POT", "SOD", "CLA", "POT", "MG2", "CAL", "IOD",
}
KNOWN_FF_FAMILIES = {
    "amber99sb-ildn", "amber99sb", "amber03", "amber14sb",
    "charmm27", "charmm36", "oplsaa", "gromos96", "gromos54a7",
}
# Aliases that appear in the wild (e.g. AMBER ports often encode "ff14sb"
# without the leading "amber"). Maps alias -> canonical name.
FF_ALIASES = {
    "ff14sb": "amber14sb",
    "ff99sb-ildn": "amber99sb-ildn",
    "ff99sb": "amber99sb",
    "ff03": "amber03",
}

# ANSI colours (only used when stdout is a TTY and --no-color isn't set).
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"


# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------

@dataclass
class CheckResult:
    """A single check's outcome.

    `status`: 'PASS' | 'WARN' | 'ERROR' | 'INFO'
    `message`: one-line summary shown next to the status glyph.
    `hints`: optional follow-up lines printed indented under the message.
    """
    status: str
    message: str
    hints: list[str] = field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return self.status == "ERROR"

    @property
    def is_warning(self) -> bool:
        return self.status == "WARN"


# --------------------------------------------------------------------------
# CLI / discovery
# --------------------------------------------------------------------------

def _discover_bundle(bundle_dir: Path) -> dict[str, Optional[Path]]:
    """Resolve the standard input bundle layout from a single directory.

    Picks the first matching file by extension. If multiple candidates exist
    (e.g. two .pdb files), the user must pass them explicitly instead.
    """
    files = list(bundle_dir.iterdir()) if bundle_dir.is_dir() else []
    by_ext: dict[str, list[Path]] = {}
    for f in files:
        if not f.is_file():
            continue
        by_ext.setdefault(f.suffix.lower(), []).append(f)

    def _pick_one(exts: Iterable[str]) -> Optional[Path]:
        for ext in exts:
            cands = by_ext.get(ext, [])
            if len(cands) == 1:
                return cands[0]
            if len(cands) > 1:
                # ambiguous — let the explicit-CLI path handle it
                return None
        return None

    return {
        "structure": _pick_one([".pdb", ".gro"]),
        "trajectory": _pick_one([".xtc", ".trr"]),
        "topology": _pick_one([".top"]),
        "itps": by_ext.get(".itp", []),
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="inspect_sim.py",
        description="Pre-flight inspection for i-gRINN job bundles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--mode", choices=["trajectory", "ensemble"], default="trajectory",
                   help="i-gRINN analysis mode the bundle is intended for (default: trajectory).")
    p.add_argument("--bundle", type=Path,
                   help="Auto-discover files in this directory (overrides explicit --structure/etc.).")
    p.add_argument("--structure", type=Path, help="Path to PDB or GRO structure file.")
    p.add_argument("--trajectory", type=Path, help="Path to XTC trajectory (trajectory mode only).")
    p.add_argument("--topology", type=Path, help="Path to TOP topology (trajectory mode only).")
    p.add_argument("--itp", type=Path, action="append", default=[],
                   help="Additional .itp include file (repeatable). "
                        "Auto-discovered when --bundle is used.")
    p.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES,
                   help=f"i-gRINN frame cap (default: {DEFAULT_MAX_FRAMES}).")
    p.add_argument("--max-traj-mb", type=int, default=DEFAULT_MAX_TRAJECTORY_MB,
                   help=f"Trajectory size limit in MB (default: {DEFAULT_MAX_TRAJECTORY_MB}).")
    p.add_argument("--max-other-mb", type=int, default=DEFAULT_MAX_OTHER_MB,
                   help=f"Per-file size limit for structure/topology/itp in MB (default: {DEFAULT_MAX_OTHER_MB}).")
    p.add_argument("--initpairfilter-cutoff", type=float, default=DEFAULT_INITPAIRFILTER_CUTOFF_A,
                   help=f"Cutoff in Å used by the lone-ligand heuristic (default: {DEFAULT_INITPAIRFILTER_CUTOFF_A}).")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colours in output.")
    args = p.parse_args(argv)

    # Bundle expansion fills in any missing explicit paths.
    if args.bundle:
        if not args.bundle.is_dir():
            p.error(f"--bundle {args.bundle!s} is not a directory")
        discovered = _discover_bundle(args.bundle)
        if not args.structure:
            args.structure = discovered["structure"]
        if not args.trajectory:
            args.trajectory = discovered["trajectory"]
        if not args.topology:
            args.topology = discovered["topology"]
        if not args.itp:
            args.itp = discovered["itps"]

    return args


# --------------------------------------------------------------------------
# Stdlib helpers (no mdtraj needed)
# --------------------------------------------------------------------------

def _file_size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def _human_size(path: Path) -> str:
    n = path.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} GB"


def _read_pdb_records(path: Path) -> list[tuple[str, str, str, int, str]]:
    """Yield (record_type, atom_name, resname, resnum, chain_id) for each
    ATOM/HETATM line in `path`. Robust against truncated lines."""
    rows = []
    try:
        with open(path, "r", errors="ignore") as f:
            for line in f:
                if not line.startswith(("ATOM", "HETATM")):
                    continue
                if len(line) < 27:
                    continue
                rec = line[0:6].strip()
                atom_name = line[12:16].strip()
                resname = line[17:20].strip()
                try:
                    resnum = int(line[22:26].strip())
                except ValueError:
                    continue
                chain = line[21:22]
                rows.append((rec, atom_name, resname, resnum, chain))
    except OSError:
        return []
    return rows


def _count_pdb_models(path: Path) -> int:
    """Count MODEL records in a PDB. Single-model PDBs without MODEL/ENDMDL
    return 1 (one model implied by the ATOM records)."""
    n_models = 0
    has_atom = False
    try:
        with open(path, "r", errors="ignore") as f:
            for line in f:
                if line.startswith("MODEL"):
                    n_models += 1
                elif line.startswith(("ATOM", "HETATM")):
                    has_atom = True
    except OSError:
        return 0
    return n_models or (1 if has_atom else 0)


def _has_cryst1(path: Path) -> bool:
    try:
        with open(path, "r", errors="ignore") as f:
            for line in f:
                if line.startswith("CRYST1"):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            a, b, c = float(parts[1]), float(parts[2]), float(parts[3])
                            return a > 0 and b > 0 and c > 0
                        except ValueError:
                            return False
                if line.startswith(("ATOM", "HETATM", "MODEL")):
                    return False
    except OSError:
        return False
    return False


def parse_top_includes(top_path: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (local_resolvable, share_tree, missing) include filenames.

    - local_resolvable: file exists in the topology's directory
    - share_tree: include path looks like a GROMACS force-field share-tree
      reference (e.g. "amber14sb.ff/forcefield.itp"); GROMACS resolves these
      from its own share dir at grompp time. NOT a missing-include error.
    - missing: a flat reference (no slash) that doesn't exist locally — the
      user really did forget to ship this file.
    """
    local, share, missing = [], [], []
    if not top_path.exists():
        return local, share, missing
    base = top_path.parent
    pat = re.compile(r'^\s*#include\s+"([^"]+)"')
    try:
        with open(top_path, "r", errors="ignore") as f:
            for line in f:
                m = pat.match(line)
                if not m:
                    continue
                inc = m.group(1)
                target = base / inc
                if target.exists():
                    local.append(inc)
                elif ".ff/" in inc:
                    # Looks like a GROMACS force-field directory reference
                    # (e.g. "amber14sb.ff/forcefield.itp"). gmx grompp
                    # resolves these from its share tree.
                    share.append(inc)
                else:
                    missing.append(inc)
    except OSError:
        pass
    return local, share, missing


def parse_top_molecules(top_path: Path) -> list[tuple[str, int]]:
    """Extract `[ molecules ]` entries as (mol_name, count). Empty if absent."""
    rows = []
    if not top_path.exists():
        return rows
    in_block = False
    try:
        with open(top_path, "r", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("["):
                    in_block = stripped.lower().startswith("[ molecules")
                    continue
                if not in_block or not stripped or stripped.startswith(";"):
                    continue
                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        rows.append((parts[0], int(parts[1])))
                    except ValueError:
                        continue
    except OSError:
        pass
    return rows


def detect_ff_family(top_path: Path, itp_paths: Iterable[Path] = ()) -> Optional[str]:
    """Best-effort FF family detection. Scans the .top text and any provided
    .itp files (since some bundles encode the FF identity in atomtypes.itp
    via "ff14SB"-style names). Returns None if nothing recognisable.
    """
    if not top_path.exists():
        return None
    candidates: list[Path] = [top_path] + [p for p in itp_paths if p.exists()]
    # Also include sibling .itps automatically — common pattern.
    for sib in top_path.parent.iterdir():
        if sib.suffix.lower() == ".itp" and sib not in candidates:
            candidates.append(sib)
    text = ""
    for path in candidates:
        try:
            text += path.read_text(errors="ignore").lower() + "\n"
        except OSError:
            continue
    for ff in sorted(KNOWN_FF_FAMILIES, key=len, reverse=True):
        if ff in text:
            return ff
    for alias, canon in sorted(FF_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias in text:
            return canon
    return None


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------

def check_structure_present(structure: Optional[Path]) -> CheckResult:
    if structure is None:
        return CheckResult("ERROR", "No structure file provided",
                           ["Pass --structure system_dry.pdb (or .gro)"])
    if not structure.exists():
        return CheckResult("ERROR", f"Structure file does not exist: {structure}")
    return CheckResult(
        "PASS",
        f"structure: {structure.name} ({_human_size(structure)})"
    )


def check_structure_extension(structure: Optional[Path]) -> CheckResult:
    if structure is None or not structure.exists():
        return CheckResult("INFO", "structure extension: skipped (no file)")
    ext = structure.suffix.lower()
    if ext in {".cif", ".mmcif"}:
        return CheckResult(
            "ERROR",
            f"structure extension: {ext} (mmCIF) is not supported by i-gRINN",
            [
                "Convert to PDB with PyMOL: load my.cif; save my.pdb",
                "Or with gemmi: gemmi convert my.cif my.pdb",
            ],
        )
    if ext not in {".pdb", ".gro"}:
        return CheckResult(
            "ERROR",
            f"structure extension: {ext} not accepted (use .pdb or .gro)",
        )
    return CheckResult("PASS", f"structure extension: {ext}")


def check_trajectory_present(mode: str, trajectory: Optional[Path]) -> CheckResult:
    if mode == "ensemble":
        if trajectory is not None:
            return CheckResult(
                "ERROR",
                "ensemble mode forbids --trajectory",
                ["Drop --trajectory; ensemble mode reads MODELs from the PDB."],
            )
        return CheckResult("INFO", "trajectory: not used in ensemble mode")
    if trajectory is None:
        return CheckResult(
            "ERROR",
            "trajectory mode requires --trajectory",
            ["Pass --trajectory traj_dry.xtc"],
        )
    if not trajectory.exists():
        return CheckResult("ERROR", f"trajectory file does not exist: {trajectory}")
    ext = trajectory.suffix.lower()
    if ext not in {".xtc", ".trr"}:
        return CheckResult(
            "ERROR",
            f"trajectory extension: {ext} not accepted (use .xtc, optionally .trr)",
        )
    return CheckResult(
        "PASS",
        f"trajectory: {trajectory.name} ({_human_size(trajectory)})",
    )


def check_topology_present(mode: str, topology: Optional[Path]) -> CheckResult:
    if mode == "ensemble":
        if topology is not None:
            return CheckResult(
                "WARN",
                "ensemble mode does not require --topology",
                ["i-gRINN regenerates topology from the multi-model PDB via pdb2gmx."],
            )
        return CheckResult("INFO", "topology: regenerated by i-gRINN in ensemble mode")
    if topology is None:
        return CheckResult(
            "ERROR",
            "trajectory mode requires --topology",
            ["Pass --topology topol_dry.top"],
        )
    if not topology.exists():
        return CheckResult("ERROR", f"topology file does not exist: {topology}")
    if topology.suffix.lower() != ".top":
        return CheckResult(
            "ERROR",
            f"topology extension: {topology.suffix} (only .top accepted as master topology)",
            [
                "If the file is an .itp, you also need a .top that #includes it.",
                "Mark only the .top with role=topology when uploading to i-gRINN.",
            ],
        )
    return CheckResult(
        "PASS",
        f"topology: {topology.name} ({_human_size(topology)})",
    )


def check_sizes(structure, trajectory, topology, itps,
                max_traj_mb: int, max_other_mb: int) -> list[CheckResult]:
    results = []
    if trajectory and trajectory.exists():
        size = _file_size_mb(trajectory)
        if size > max_traj_mb:
            results.append(CheckResult(
                "ERROR",
                f"trajectory size: {size:.1f} MB exceeds i-gRINN limit ({max_traj_mb} MB)",
                [
                    f"Stride to fit: gmx trjconv -f traj.xtc -o traj_skip.xtc -skip N",
                    f"With your current size, try -skip {int(size / max_traj_mb) + 1}.",
                ],
            ))
        else:
            results.append(CheckResult(
                "PASS",
                f"trajectory size: {size:.1f}/{max_traj_mb} MB",
            ))
    for label, path in [("structure", structure), ("topology", topology)]:
        if path and path.exists():
            size = _file_size_mb(path)
            if size > max_other_mb:
                results.append(CheckResult(
                    "ERROR",
                    f"{label} size: {size:.1f} MB exceeds i-gRINN limit ({max_other_mb} MB per file)",
                ))
    for itp in itps:
        if itp.exists() and _file_size_mb(itp) > max_other_mb:
            results.append(CheckResult(
                "ERROR",
                f"itp size: {itp.name} is {_file_size_mb(itp):.1f} MB (limit {max_other_mb} MB)",
            ))
    return results


def check_frame_count(trajectory: Optional[Path], structure: Optional[Path],
                      max_frames: int) -> CheckResult:
    if trajectory is None or not trajectory.exists():
        return CheckResult("INFO", "frame count: skipped (no trajectory)")
    try:
        import mdtraj as md
    except ImportError:
        return CheckResult(
            "WARN",
            "frame count: skipped (mdtraj not installed)",
            ["Install with: pip install mdtraj"],
        )
    try:
        # iterload counts frames without holding the whole trajectory in RAM.
        n = 0
        for chunk in md.iterload(str(trajectory), top=str(structure), chunk=1000):
            n += chunk.n_frames
            if n > max_frames + 100:
                break  # plenty of headroom to know we're over the cap
    except Exception as e:
        return CheckResult(
            "WARN",
            f"frame count: could not read ({e.__class__.__name__})",
        )
    if n > max_frames:
        return CheckResult(
            "WARN",
            f"frame count: {n} exceeds i-gRINN cap ({max_frames})",
            [
                f"Stride before submission: gmx trjconv -skip {(n // max_frames) + 1} ...",
                "Or set max_frames higher if your local i-gRINN deployment allows.",
            ],
        )
    return CheckResult("PASS", f"frame count: {n}/{max_frames}")


def check_mode_consistency(mode: str, structure: Optional[Path]) -> CheckResult:
    if structure is None or not structure.exists():
        return CheckResult("INFO", "mode consistency: skipped (no structure)")
    if structure.suffix.lower() not in {".pdb", ".gro"}:
        return CheckResult("INFO", "mode consistency: skipped (not a PDB/GRO)")
    n_models = _count_pdb_models(structure)
    if mode == "ensemble":
        if n_models < 2:
            return CheckResult(
                "ERROR",
                f"ensemble mode requires ≥2 MODEL records; found {n_models}",
                [
                    "Wrap each conformer in MODEL/ENDMDL pairs.",
                    "Or re-run i-gRINN in trajectory mode with an XTC instead.",
                ],
            )
        return CheckResult("PASS", f"ensemble mode: {n_models} MODELs")
    # trajectory mode
    if n_models > 1:
        return CheckResult(
            "WARN",
            f"trajectory mode but PDB has {n_models} MODELs",
            [
                "i-gRINN reads only the first model as the static reference.",
                "If you want every conformer analysed, switch to ensemble mode.",
            ],
        )
    return CheckResult("PASS", f"trajectory mode: 1 MODEL in PDB")


def check_chain_ids(structure: Optional[Path]) -> CheckResult:
    if structure is None or not structure.exists():
        return CheckResult("INFO", "chain IDs: skipped (no structure)")
    if structure.suffix.lower() != ".pdb":
        return CheckResult("INFO", "chain IDs: skipped (not a PDB)")
    rows = _read_pdb_records(structure)
    if not rows:
        return CheckResult("INFO", "chain IDs: no ATOM records found")
    chains = sorted({c for _, _, _, _, c in rows})
    # Detect resnum reset within the same chain (the mdtraj GRO->PDB pathology).
    last_per_chain: dict[str, int] = {}
    reset_chain: Optional[str] = None
    reset_count = 0
    for _, _, _, resnum, chain in rows:
        prev = last_per_chain.get(chain)
        if prev is not None and resnum < prev:
            reset_chain = chain
            reset_count += 1
        last_per_chain[chain] = max(prev or resnum, resnum)
    if reset_chain is not None:
        return CheckResult(
            "WARN",
            f"chain IDs: only {len(chains)} unique chain(s) {chains} but resnums reset {reset_count} time(s)",
            [
                "Duplicate (chain, resnum) tuples are collapsed by ProDy and lose chains/ligands.",
                "i-gRINN ≥ 2024.1 auto-corrects via topology when --top is provided (Heuristic 3).",
                "If you submit without a topology, fix chain IDs first (e.g. with PyMOL alter chain).",
            ],
        )
    return CheckResult("PASS", f"chain IDs: {len(chains)} unique chain(s) {chains}")


def check_topology_includes(topology: Optional[Path], itps: list[Path]) -> CheckResult:
    if topology is None or not topology.exists():
        return CheckResult("INFO", "topology #includes: skipped (no .top)")
    local, share, missing = parse_top_includes(topology)
    if missing:
        return CheckResult(
            "ERROR",
            f"topology #includes: {len(missing)} unresolved",
            [f"Missing in {topology.parent}: {', '.join(missing[:5])}"],
        )
    parts = [f"{len(local)} local"]
    if share:
        parts.append(f"{len(share)} share-tree (resolved by GROMACS at grompp time)")
    return CheckResult("PASS", f"topology #includes: {', '.join(parts)}")


def check_residue_coverage(structure: Optional[Path], topology: Optional[Path]) -> CheckResult:
    if structure is None or topology is None:
        return CheckResult("INFO", "residue coverage: skipped (need both PDB and TOP)")
    if structure.suffix.lower() != ".pdb":
        return CheckResult("INFO", "residue coverage: skipped (structure is not a PDB)")
    rows = _read_pdb_records(structure)
    if not rows:
        return CheckResult("INFO", "residue coverage: no ATOM records found")
    pdb_resnames = {rname for _, _, rname, _, _ in rows}
    top_mols = {mol.upper() for mol, _ in parse_top_molecules(topology)}
    # We can't perfectly map every resname to a [molecules] entry without
    # parsing each .itp's [moleculetype]/[atoms] block. Surface this as an
    # informational summary instead of a hard error.
    text = topology.read_text(errors="ignore").upper()
    unrecognised = sorted(
        r for r in pdb_resnames
        if r not in STD_AMINO_ACIDS and r not in STD_WATERS_IONS
        and r.upper() not in top_mols
        and r.upper() not in text
    )
    if unrecognised:
        return CheckResult(
            "WARN",
            f"residue coverage: {len(unrecognised)} non-standard residue(s) not found in topology",
            [
                f"Unrecognised: {', '.join(unrecognised[:8])}",
                "Provide an .itp with [ moleculetype ]/[ atoms ] for each, or remove them.",
            ],
        )
    return CheckResult(
        "PASS",
        f"residue coverage: all {len(pdb_resnames)} unique residue type(s) accounted for",
    )


def check_solvent_presence(structure: Optional[Path]) -> CheckResult:
    if structure is None or not structure.exists() or structure.suffix.lower() != ".pdb":
        return CheckResult("INFO", "solvent: skipped (no PDB)")
    rows = _read_pdb_records(structure)
    solvent_atoms = sum(1 for _, _, rname, _, _ in rows if rname in STD_WATERS_IONS)
    if solvent_atoms > 0:
        return CheckResult(
            "WARN",
            f"solvent: PDB contains {solvent_atoms} water/ion atom(s)",
            [
                "i-gRINN expects a 'dry' system. Strip waters/ions before submission:",
                "  gmx trjconv -s topol.tpr -f traj.xtc -o traj_dry.xtc <<< 'Protein'",
                "  gmx editconf -f system.gro -o system_dry.pdb -ndef ...",
                "Otherwise the energy matrix bloats and selections may pick up solvent.",
            ],
        )
    return CheckResult("PASS", "solvent: PDB is dry (no waters/ions)")


def check_box_vectors(structure: Optional[Path]) -> CheckResult:
    if structure is None or not structure.exists() or structure.suffix.lower() != ".pdb":
        return CheckResult("INFO", "box vectors: skipped (no PDB)")
    if _has_cryst1(structure):
        return CheckResult("PASS", "box vectors: CRYST1 present")
    return CheckResult(
        "WARN",
        "box vectors: PDB lacks CRYST1 record",
        [
            "i-gRINN auto-injects a default cubic box (R1.g fix), but a real one is preferable.",
            "Use gmx editconf -f in.pdb -o out.pdb -box X Y Z to add CRYST1.",
        ],
    )


def detect_lone_ligand(structure: Optional[Path], trajectory: Optional[Path],
                        cutoff_A: float) -> CheckResult:
    """Heuristic: if a non-standard residue's COM is > cutoff Å from every
    standard residue at frame 0, the static pair filter will cull all its pairs
    and the user should switch to pair_filter_mode=dynamic."""
    if structure is None or not structure.exists():
        return CheckResult("INFO", "lone-ligand check: skipped (no structure)")
    if structure.suffix.lower() != ".pdb":
        return CheckResult("INFO", "lone-ligand check: skipped (not a PDB)")
    rows = _read_pdb_records(structure)
    if not rows:
        return CheckResult("INFO", "lone-ligand check: no atoms")
    # Identify candidate ligands (non-standard, non-solvent residues)
    ligand_atoms: dict[tuple[str, int], list[tuple[float, float, float]]] = {}
    protein_atoms: list[tuple[float, float, float]] = []
    # Re-walk the file to grab coordinates (the simple parser above didn't keep them)
    with open(structure, "r", errors="ignore") as f:
        for line in f:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            if len(line) < 54:
                continue
            try:
                rname = line[17:20].strip()
                resnum = int(line[22:26].strip())
                chain = line[21:22]
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
            except ValueError:
                continue
            if rname in STD_AMINO_ACIDS:
                protein_atoms.append((x, y, z))
            elif rname not in STD_WATERS_IONS:
                ligand_atoms.setdefault((rname, resnum), []).append((x, y, z))
    if not ligand_atoms or not protein_atoms:
        return CheckResult("PASS", "lone-ligand check: no candidate ligand or no protein")

    # Compute per-residue COMs and find each ligand's nearest-protein-residue distance
    def com(coords: list[tuple[float, float, float]]) -> tuple[float, float, float]:
        n = len(coords)
        return (sum(c[0] for c in coords) / n,
                sum(c[1] for c in coords) / n,
                sum(c[2] for c in coords) / n)

    prot_com = com(protein_atoms)
    far_ligands = []
    for (rname, resnum), coords in ligand_atoms.items():
        lcom = com(coords)
        # Use COM-COM as a coarse approximation; the script doesn't try to be
        # exact, just to flag obvious pathologies.
        d = ((lcom[0] - prot_com[0]) ** 2
             + (lcom[1] - prot_com[1]) ** 2
             + (lcom[2] - prot_com[2]) ** 2) ** 0.5
        if d > cutoff_A:
            far_ligands.append((rname, resnum, d))
    if far_ligands:
        sample = ", ".join(f"{r}{n} ({d:.1f} Å)" for r, n, d in far_ligands[:3])
        return CheckResult(
            "WARN",
            f"lone-ligand: {len(far_ligands)} ligand(s) > {cutoff_A:.1f} Å from protein at frame 0",
            [
                f"Examples: {sample}",
                "i-gRINN's default 'static' pair filter will cull all their pairs.",
                "Pass pair_filter_mode=dynamic in Advanced Parameters to scan every frame.",
                "(Especially relevant for binding/unbinding trajectories.)",
            ],
        )
    return CheckResult("PASS", "lone-ligand: all non-standard residues near protein at frame 0")


def detect_force_field(topology: Optional[Path], itps: list[Path]) -> CheckResult:
    if topology is None or not topology.exists():
        return CheckResult("INFO", "force field: skipped (no .top)")
    ff = detect_ff_family(topology, itps)
    if ff is None:
        return CheckResult(
            "WARN",
            "force field: could not identify a known FF family",
            [
                "Known families: " + ", ".join(sorted(KNOWN_FF_FAMILIES)),
                "i-gRINN may still run if your topology is internally consistent.",
            ],
        )
    return CheckResult("PASS", f"force field: detected '{ff}'")


def print_bundle_summary(mode: str, structure, trajectory, topology, itps) -> CheckResult:
    parts = []
    if structure: parts.append(f"structure={structure.name}")
    if trajectory: parts.append(f"trajectory={trajectory.name}")
    if topology: parts.append(f"topology={topology.name}")
    if itps: parts.append(f"itps={len(itps)}")
    msg = f"bundle ({mode} mode): " + ("; ".join(parts) or "<empty>")
    return CheckResult("INFO", msg)


# --------------------------------------------------------------------------
# Output formatting
# --------------------------------------------------------------------------

def _glyph(status: str, color: bool) -> str:
    g = {"PASS": "✓", "WARN": "⚠", "ERROR": "✗", "INFO": "·"}.get(status, "?")
    if not color:
        return f"[ {g} ]"
    c = {"PASS": GREEN, "WARN": YELLOW, "ERROR": RED, "INFO": DIM}.get(status, "")
    return f"[ {c}{g}{RESET} ]"


def render(results: list[CheckResult], mode: str, color: bool) -> str:
    out = []
    head = f"gRINN pre-flight inspection — {mode} mode"
    out.append(f"{BOLD}{head}{RESET}" if color else head)
    out.append("=" * 68)
    for r in results:
        out.append(f"{_glyph(r.status, color)} {r.message}")
        for h in r.hints:
            out.append(f"        → {h}")
    out.append("")
    n_errors = sum(1 for r in results if r.is_error)
    n_warnings = sum(1 for r in results if r.is_warning)
    verdict = (
        "bundle is acceptable" if n_errors == 0 else "bundle would fail at i-gRINN"
    )
    summary = (
        f"Summary: {n_errors} error(s), {n_warnings} warning(s) — {verdict}."
    )
    if color:
        col = RED if n_errors else (YELLOW if n_warnings else GREEN)
        summary = f"{col}{summary}{RESET}"
    out.append(summary)
    return "\n".join(out)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def run_checks(args: argparse.Namespace) -> list[CheckResult]:
    s, t, top, itps = args.structure, args.trajectory, args.topology, list(args.itp)
    results: list[CheckResult] = [
        print_bundle_summary(args.mode, s, t, top, itps),
        check_structure_present(s),
        check_structure_extension(s),
        check_trajectory_present(args.mode, t),
        check_topology_present(args.mode, top),
        *check_sizes(s, t, top, itps, args.max_traj_mb, args.max_other_mb),
        check_frame_count(t, s, args.max_frames),
        check_mode_consistency(args.mode, s),
        check_chain_ids(s),
        check_topology_includes(top, itps),
        check_residue_coverage(s, top),
        check_solvent_presence(s),
        check_box_vectors(s),
        detect_lone_ligand(s, t, args.initpairfilter_cutoff),
        detect_force_field(top, itps),
    ]
    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    color = sys.stdout.isatty() and not args.no_color
    results = run_checks(args)
    print(render(results, args.mode, color))
    if any(r.is_error for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
