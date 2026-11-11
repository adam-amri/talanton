"""Recalcul du classeur par un vrai tableur, puis rapprochement avec le moteur Python.

openpyxl écrit les formules sans leurs résultats. LibreOffice (gratuit) les
calcule en ligne de commande : on peut alors relire les valeurs, vérifier qu'il
n'y a aucune erreur de formule et comparer chaque chiffre clé à celui du moteur.
Sans LibreOffice, le classeur reste valide : Excel calcule tout à l'ouverture,
et l'onglet Contrôles fait le même rapprochement.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

EMPLACEMENTS_USUELS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)
ERREURS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "Err:")


def trouver_libreoffice() -> str | None:
    for nom in ("soffice", "libreoffice"):
        chemin = shutil.which(nom)
        if chemin:
            return chemin
    for chemin in EMPLACEMENTS_USUELS:
        if Path(chemin).exists():
            return chemin
    return None


def recalculer(fichier: Path, delai_s: int = 180) -> bool:
    """Fait calculer toutes les formules par LibreOffice et réécrit le fichier avec leurs valeurs.

    Renvoie False si LibreOffice est absent (le fichier n'est alors pas touché).
    """
    soffice = trouver_libreoffice()
    if soffice is None:
        return False
    fichier = Path(fichier).resolve()
    with tempfile.TemporaryDirectory(prefix="talanton_") as tmp:
        profil, sortie = Path(tmp) / "profil", Path(tmp) / "sortie"
        commande = [soffice, "--headless", "--norestore", f"-env:UserInstallation={profil.as_uri()}",
                    "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(sortie), str(fichier)]
        resultat = subprocess.run(commande, capture_output=True, timeout=delai_s, check=False)
        produit = sortie / fichier.name
        if not produit.exists():
            raise RuntimeError("LibreOffice n'a pas produit de fichier : "
                               + resultat.stderr.decode(errors="replace")[:500])
        shutil.copyfile(produit, fichier)
    return True


@dataclass
class Rapprochement:
    ecarts: dict[str, tuple[float, float]]        # clé -> (Excel, Python) quand ils diffèrent
    erreurs_formules: list[str]                   # cellules en erreur
    cellules_vides: list[str]                     # formules restées sans valeur
    statut: str                                   # contenu de la cellule de statut d'ensemble
    n_formules: int

    @property
    def conforme(self) -> bool:
        return not (self.ecarts or self.erreurs_formules or self.cellules_vides) and "ERREUR" not in self.statut


def rapprocher(fichier: Path, registre: dict[str, tuple[str, str]], points: dict[str, float],
               tolerance: float = 1e-6) -> Rapprochement:
    """Compare les valeurs calculées par le tableur aux chiffres du moteur Python."""
    formules = load_workbook(fichier, data_only=False)
    valeurs = load_workbook(fichier, data_only=True)
    erreurs, vides, n = [], [], 0
    for ws in formules.worksheets:
        for ligne in ws.iter_rows():
            for cell in ligne:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    n += 1
                    v = valeurs[ws.title][cell.coordinate].value
                    if v is None:
                        vides.append(f"{ws.title}!{cell.coordinate}")
                    elif isinstance(v, str) and v.startswith(ERREURS):
                        erreurs.append(f"{ws.title}!{cell.coordinate} = {v}")
    ecarts = {}
    for cle, attendu in points.items():
        feuille, adresse = registre[cle]
        obtenu = valeurs[feuille][adresse].value
        if not isinstance(obtenu, (int, float)) or abs(obtenu - attendu) > tolerance * max(1.0, abs(attendu)):
            ecarts[cle] = (obtenu, attendu)
    feuille, adresse = registre["controles.statut"]
    statut = str(valeurs[feuille][adresse].value)
    return Rapprochement(ecarts, erreurs, vides, statut, n)
