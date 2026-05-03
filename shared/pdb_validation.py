"""Shared PDB structure validation used by the frontend upload-time check.

The authoritative validation lives in gRINN's preflight (--test-only); this
module is purely for fast UX feedback at file-pick time so the user does not
have to wait for a backend round-trip + container preflight before seeing
that a single-structure PDB is invalid for ensemble mode.
"""
try:
    # Backend context: repo root on sys.path → shared is a package.
    from shared.config import get_config
except ImportError:
    # Frontend context: shared/ itself is on sys.path → bare-name import.
    from config import get_config

ENSEMBLE_SINGLE_STRUCTURE_ERROR = (
    "Ensemble mode requires a multi-model PDB file (at least 2 MODEL records). "
    "This file contains only a single structure. "
    "Please upload a multi-model PDB, or switch to Trajectory mode."
)

MMCIF_NOT_SUPPORTED_ERROR = (
    "mmCIF format (.cif/.mmcif) is not supported. The underlying GROMACS "
    "engine reads only legacy PDB. Please convert to PDB first (e.g. "
    "`gemmi convert in.cif out.pdb`, or in PyMOL: `save out.pdb`)."
)


def validate_pdb_multimodel(file_path: str, input_mode: str) -> dict:
    """Count MODEL records and return a structured validation result.

    Returns dict with keys: model_count (int), is_multimodel (bool),
    warning (str|None), error (str|None).
    """
    result = {
        'model_count': 0,
        'is_multimodel': False,
        'warning': None,
        'error': None,
    }

    try:
        with open(file_path, 'r') as fh:
            model_count = 0
            endmdl_count = 0
            has_atom_records = False

            for line in fh:
                record_type = line[:6].strip()
                if record_type == 'MODEL':
                    model_count += 1
                elif record_type == 'ENDMDL':
                    endmdl_count += 1
                elif record_type in ('ATOM', 'HETATM'):
                    has_atom_records = True

            result['model_count'] = model_count
            result['is_multimodel'] = model_count > 1

            if model_count > 0 and model_count != endmdl_count:
                result['error'] = (
                    f"Mismatched MODEL/ENDMDL records "
                    f"({model_count} MODEL vs {endmdl_count} ENDMDL)"
                )
                return result

            if input_mode == 'ensemble':
                if model_count == 0:
                    if has_atom_records:
                        result['error'] = ENSEMBLE_SINGLE_STRUCTURE_ERROR
                        result['model_count'] = 1
                    else:
                        result['error'] = "PDB file contains no atom coordinates"
                elif model_count == 1:
                    result['error'] = ENSEMBLE_SINGLE_STRUCTURE_ERROR
                else:
                    cfg = get_config()
                    if cfg.max_frames and model_count > cfg.max_frames:
                        result['error'] = (
                            f"PDB has {model_count} models, which exceeds the limit "
                            f"of {cfg.max_frames}"
                        )

    except Exception as e:
        result['error'] = f"Failed to parse PDB file: {str(e)}"

    return result
