"""Mise en forme du classeur, selon les conventions des modèles financiers.

Couleur du texte :
    bleu   -> chiffre saisi en dur (donnée publiée ou hypothèse)
    noir   -> formule
    vert   -> lien vers un autre onglet
Fond jaune pâle -> hypothèse à modifier.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

POLICE = "Arial"
TAILLE = 10
BLEU, NOIR, VERT, GRIS, BLANC = "0000FF", "000000", "008000", "595959", "FFFFFF"
ENCRE = "1F2A44"            # titres et bandeaux
JAUNE_PALE = "FFF9D6"
GRIS_PALE = "F2F2F2"

FMT_M = '#,##0.0;(#,##0.0);"-"'              # millions, une décimale
FMT_PCT = '0.0%;(0.0%);"-"'
FMT_X = '0.0"x";(0.0"x");"-"'
FMT_PRIX = '#,##0.00;(#,##0.00);"-"'
FMT_DATE = "dd/mm/yyyy"
FMT_NB = "0.00"
FMT_ENTIER = "0"

COULEURS = {"saisie": BLEU, "hypothese": BLEU, "calcul": NOIR, "lien": VERT, "note": GRIS}
FIN = Side(style="thin", color="A6A6A6")


def police(couleur: str = NOIR, gras: bool = False, italique: bool = False, taille: int = TAILLE) -> Font:
    return Font(name=POLICE, size=taille, color=couleur, bold=gras, italic=italique)


def appliquer(cellule, style: str = "calcul", fmt: str | None = None, gras: bool = False,
              total: bool = False, centre: bool = False) -> None:
    cellule.font = police(COULEURS.get(style, NOIR), gras=gras or total, italique=(style == "note"))
    if style == "hypothese":
        cellule.fill = PatternFill("solid", start_color=JAUNE_PALE)
    if fmt:
        cellule.number_format = fmt
    if total:
        cellule.border = Border(top=FIN)
    if centre:
        cellule.alignment = Alignment(horizontal="center")
    elif style == "note":
        cellule.alignment = Alignment(horizontal="left", indent=1)


def bandeau(ws, ligne: int, texte: str, derniere_colonne: int) -> None:
    """Titre de section : bandeau foncé sur toute la largeur du tableau."""
    for c in range(1, derniere_colonne + 1):
        cell = ws.cell(row=ligne, column=c)
        cell.fill = PatternFill("solid", start_color=ENCRE)
        cell.font = police(BLANC, gras=True)
    ws.cell(row=ligne, column=1, value=texte)


def entete(ws, ligne: int, textes: dict[str, str], gauche: tuple[str, ...] = ()) -> None:
    """En-têtes de colonnes : gras, fond gris, alignés à droite (à gauche pour le texte)."""
    for col, texte in textes.items():
        cell = ws[f"{col}{ligne}"]
        cell.value = texte
        cell.font = police(gras=True)
        cell.fill = PatternFill("solid", start_color=GRIS_PALE)
        a_gauche_ = col == "A" or col in gauche
        cell.alignment = Alignment(horizontal="left" if a_gauche_ else "right", indent=1 if col in gauche else 0)
        cell.border = Border(bottom=FIN)


def largeurs(ws, premiere: float, autres: float, n: int, extra: dict[str, float] | None = None) -> None:
    ws.column_dimensions["A"].width = premiere
    for i in range(2, n + 1):
        ws.column_dimensions[get_column_letter(i)].width = autres
    for col, w in (extra or {}).items():
        ws.column_dimensions[col].width = w


def a_gauche(cellule) -> None:
    cellule.alignment = Alignment(horizontal="left")


def fond_hypothese(cellule) -> None:
    cellule.fill = PatternFill("solid", start_color=JAUNE_PALE)
