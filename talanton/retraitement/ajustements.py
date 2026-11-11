"""Ajustements d'analyste : la couche de jugement, écrite dans un fichier TOML.

Exemple (exemples/retraitements/MAT.toml) :

    [capex]
    source = "10-K, tableau de flux : deux lignes d'investissement additionnées"
    "2025-12-31" = 181.992

    [ebitda]
    source = "Communiqué du T3 2026 : remboursements de droits de douane"
    "LTM" = -88.0

    [resultat_net]
    source = "Plus-value non récurrente"
    "LTM" = -150.0

Les montants sont en millions. Les clés sont des fins d'exercice (AAAA-MM-JJ)
ou « LTM ». Un ajustement d'EBITDA s'ajoute à l'EBITDA publié : un montant
négatif retire un produit non récurrent, un montant positif réintègre une charge.
Un ajustement de résultat net (après impôt) ne sert qu'au PER des comparables.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Ajustements:
    capex: dict[str, float] = field(default_factory=dict)
    ebitda: dict[str, float] = field(default_factory=dict)
    resultat_net: dict[str, float] = field(default_factory=dict)
    source_capex: str = ""
    source_ebitda: str = ""
    source_resultat_net: str = ""

    @property
    def vide(self) -> bool:
        return not (self.capex or self.ebitda or self.resultat_net)


def charger_ajustements(fichier: Path | None) -> Ajustements:
    if fichier is None or not Path(fichier).exists():
        return Ajustements()
    brut = tomllib.loads(Path(fichier).read_text(encoding="utf-8"))
    capex = dict(brut.get("capex", {}))
    ebitda = dict(brut.get("ebitda", {}))
    rn = dict(brut.get("resultat_net", {}))
    return Ajustements(
        source_capex=str(capex.pop("source", "")),
        source_ebitda=str(ebitda.pop("source", "")),
        source_resultat_net=str(rn.pop("source", "")),
        capex={k: float(v) for k, v in capex.items()},
        ebitda={k: float(v) for k, v in ebitda.items()},
        resultat_net={k: float(v) for k, v in rn.items()},
    )
