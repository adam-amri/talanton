"""Recalculation of the workbook by a real spreadsheet, then reconciliation with the Python engine.

openpyxl writes formulas without their results. LibreOffice (free) computes
them from the command line: the values can then be read back, to check that no
formula is in error and to compare every key figure with the engine's.
Without LibreOffice the workbook remains valid: Excel computes everything when
the file is opened, and the Checks sheet does the same reconciliation.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

USUAL_LOCATIONS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)
ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "Err:")


def find_libreoffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    for path in USUAL_LOCATIONS:
        if Path(path).exists():
            return path
    return None


def recalculate(file: Path, timeout_s: int = 180) -> bool:
    """Has LibreOffice compute every formula and rewrites the file with their values.

    Returns False when LibreOffice is absent (the file is then left untouched).
    """
    soffice = find_libreoffice()
    if soffice is None:
        return False
    file = Path(file).resolve()
    with tempfile.TemporaryDirectory(prefix="talanton_") as tmp:
        profile, out = Path(tmp) / "profile", Path(tmp) / "out"
        command = [soffice, "--headless", "--norestore", f"-env:UserInstallation={profile.as_uri()}",
                   "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(file)]
        result = subprocess.run(command, capture_output=True, timeout=timeout_s, check=False)
        produced = out / file.name
        if not produced.exists():
            raise RuntimeError("LibreOffice produced no file: " + result.stderr.decode(errors="replace")[:500])
        shutil.copyfile(produced, file)
    return True


@dataclass
class Reconciliation:
    gaps: dict[str, tuple[float, float]]          # key -> (Excel, Python) when they differ
    formula_errors: list[str]                     # cells in error
    empty_cells: list[str]                        # formulas left without a value
    status: str                                   # content of the overall status cell
    n_formulas: int

    @property
    def ok(self) -> bool:
        return not (self.gaps or self.formula_errors or self.empty_cells) and "ERROR" not in self.status


def reconcile(file: Path, registry: dict[str, tuple[str, str]], points: dict[str, float],
              tolerance: float = 1e-6) -> Reconciliation:
    """Compares the values computed by the spreadsheet with the figures of the Python engine."""
    formulas = load_workbook(file, data_only=False)
    values = load_workbook(file, data_only=True)
    errors, empty, n = [], [], 0
    for ws in formulas.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    n += 1
                    v = values[ws.title][cell.coordinate].value
                    if v is None:
                        empty.append(f"{ws.title}!{cell.coordinate}")
                    elif isinstance(v, str) and v.startswith(ERRORS):
                        errors.append(f"{ws.title}!{cell.coordinate} = {v}")
    gaps = {}
    for key, expected in points.items():
        sheet, address = registry[key]
        got = values[sheet][address].value
        if not isinstance(got, (int, float)) or abs(got - expected) > tolerance * max(1.0, abs(expected)):
            gaps[key] = (got, expected)
    sheet, address = registry["checks.status"]
    status = str(values[sheet][address].value)
    return Reconciliation(gaps, errors, empty, status, n)
