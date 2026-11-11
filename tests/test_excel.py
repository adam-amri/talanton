"""Classeur Excel : les formules doivent redonner exactement les chiffres du moteur Python.

Le rapprochement fait recalculer le classeur par LibreOffice. Sans LibreOffice
sur la machine, ces tests sont ignorés (les autres continuent de tourner).
"""

from datetime import date

import pytest
from openpyxl import load_workbook

from talanton.controles import rapprocher, recalculer, trouver_libreoffice, verifier
from talanton.excel import construire_classeur
from talanton.moteur import calculer

ONGLETS = ["Synthèse", "Hypothèses", "Historique", "Projections", "DCF", "Comparables", "LBO",
           "Sensibilités", "Contrôles"]
sans_libreoffice = pytest.mark.skipif(trouver_libreoffice() is None, reason="LibreOffice absent")


def _ecrire(res, dossier):
    wb, registre = construire_classeur(res, date(2026, 11, 10))
    fichier = dossier / "modele.xlsx"
    wb.save(fichier)
    return fichier, registre


def test_structure_du_classeur(resultat, tmp_path):
    fichier, registre = _ecrire(resultat, tmp_path)
    wb = load_workbook(fichier)
    assert wb.sheetnames == ONGLETS
    formules = [c.value for ws in wb for ligne in ws.iter_rows() for c in ligne
                if isinstance(c.value, str) and c.value.startswith("=")]
    assert len(formules) > 800
    assert not [f for f in formules if "#REF" in f]
    assert set(resultat.points_de_controle()) <= set(registre)


def test_les_projections_ne_contiennent_aucun_chiffre_en_dur(resultat, tmp_path):
    fichier, _ = _ecrire(resultat, tmp_path)
    for onglet in ("Projections", "DCF", "LBO", "Sensibilités"):
        for ligne in load_workbook(fichier)[onglet].iter_rows(min_row=5):
            for c in ligne[1:]:
                if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                    # seule exception : les années de sortie de la table de sensibilité (3, 4, 5)
                    assert onglet == "Sensibilités" and c.value in (3, 4, 5), f"{onglet}!{c.coordinate}"


def test_verifications_python(resultat):
    niveaux = [niveau for niveau, _ in verifier(resultat)]
    assert "ERREUR" not in niveaux


@sans_libreoffice
def test_excel_egale_python_cas_de_base(resultat, tmp_path):
    fichier, registre = _ecrire(resultat, tmp_path)
    assert recalculer(fichier)
    rap = rapprocher(fichier, registre, resultat.points_de_controle())
    assert rap.ecarts == {} and rap.erreurs_formules == [] and rap.cellules_vides == []
    assert rap.statut.startswith("Cohérent")


@sans_libreoffice
def test_excel_egale_python_hypotheses_modifiees(donnees, tmp_path):
    """Même rapprochement après avoir bousculé les hypothèses : les formules suivent."""
    surcharges = tmp_path / "hyp.toml"
    surcharges.write_text(
        "croissance = [0.06, 0.05, 0.04, 0.03, 0.03, 0.025]\n"
        "marge_ebitda = [0.12, 0.125, 0.13, 0.135, 0.14, 0.145]\n"
        "distributions = [308.408, 200, 200, 200, 200, 200]\n"
        "dilution = 6.5\nautres_ajustements = 120\ntaux_is = 0.27\nmi_annee = 0\n"
        "date_valo = 2026-11-09\ncroissance_perpetuelle = 0.025\nmultiple_sortie_dcf = 10.0\n"
        "prime_acquisition = 0.4\nlevier = 4.0\ntaux_lbo = 0.095\namort_pct = 0.05\nsweep_pct = 0.5\n"
        "ecart_multiple_sortie = -1.0\ntri_cible = 0.18\nfrais_transaction = 0.03\n"
        "pas_wacc = 0.0025\npas_multiple = 0.5\npoids_blume = 1.0\nprime_specifique = 0.01\n")
    res = calculer(*donnees, fichier_hypotheses=surcharges)
    assert res.lbo.treso_fin[-1] > res.hyp.treso_min          # sweep partiel : la trésorerie s'accumule
    fichier, registre = _ecrire(res, tmp_path)
    assert recalculer(fichier)
    rap = rapprocher(fichier, registre, res.points_de_controle())
    assert rap.ecarts == {} and rap.erreurs_formules == [] and rap.cellules_vides == []


@sans_libreoffice
def test_tables_de_sensibilite_et_synthese(resultat, tmp_path):
    fichier, _ = _ecrire(resultat, tmp_path)
    recalculer(fichier)
    wb = load_workbook(fichier, data_only=True)
    se, sy = wb["Sensibilités"], wb["Synthèse"]
    tables = ((5, resultat.sensi.dcf_gordon), (13, resultat.sensi.dcf_multiple),
              (21, resultat.sensi.lbo_sortie), (29, resultat.sensi.lbo_prime))
    for tete, attendu in tables:
        for i, ligne in enumerate(attendu):
            for j, valeur in enumerate(ligne):
                assert se.cell(row=tete + 1 + i, column=3 + j).value == pytest.approx(valeur, rel=1e-9)
    lignes = {sy.cell(row=r, column=1).value: (sy.cell(row=r, column=2).value, sy.cell(row=r, column=3).value)
              for r in range(1, 40)}
    for libelle, bas, haut in resultat.football:
        trouve = next(v for k, v in lignes.items() if k and (k == libelle or k.startswith(libelle + " (")))
        assert trouve == pytest.approx((bas, haut), rel=1e-9)
