# Talanton
adaszadzadzadazdazdqsdzadazzqszdasdzaqsdaqdsqadxaqzdqazsd
D'un ticker à un modèle de valorisation M&A / LBO dans Excel, avec de vraies formules.

Talanton récupère les comptes publiés d'une société cotée, les met au format banque, projette ses trois états financiers, la valorise par DCF et par comparables, simule son rachat par un fonds (LBO), puis écrit le tout dans un classeur Excel où chaque chiffre est une formule : on change une hypothèse, tout se recalcule.

Le nom vient du grec τάλαντον : le talent, à la fois unité de poids et unité de monnaie. Valoriser, c'est peser.

> Version 0.1, prototype. Projet pédagogique : rien de ce que produit Talanton n'est un conseil en investissement.

## Ce que ça donne

Exemple fourni : Mattel (MAT), comptes au 30 septembre 2026, cours du 9 novembre 2026.

```
MATTEL INC /DE/ (MAT), cours 15.59 $, valeur d'entreprise 6,245 M$
  DCF, croissance perpétuelle :  29.42 $ par action (WACC 6.61%)
  DCF, multiple de sortie     :  26.31 $ par action
  Comparables, VE/EBITDA médian :  18.60 $ par action
  LBO à 30% de prime : TRI 15.2%, multiple de la mise 2.03x
  Prix maximum d'un fonds visant 20% de TRI : 14.00 $ par action

Rapprochement : 898 formules recalculées sans erreur, Excel = Python sur 21 chiffres clés.
Classeur : exemples/sorties/MAT_modele.xlsx
```

Ces valeurs découlent d'hypothèses par défaut, mécaniques. Elles servent de point de départ : le travail d'analyste commence dans l'onglet Hypothèses.

Le classeur produit (`exemples/sorties/MAT_modele.xlsx`) contient neuf onglets :

| Onglet | Contenu |
|---|---|
| Synthèse | Fourchettes de valeur par action (football field), résultat du LBO, état des contrôles |
| Hypothèses | Toutes les cellules modifiables, en bleu sur fond jaune, avec la justification de chaque valeur proposée |
| Historique | Cinq exercices retraités et les douze derniers mois, avec la balise SEC d'origine de chaque ligne |
| Projections | Compte de résultat, flux et bilan sur six exercices |
| DCF | Flux disponibles, deux valeurs terminales, passage à la valeur par action |
| Comparables | Multiples des pairs, statistiques, valeur implicite de la cible |
| LBO | Prix, financement, plan de remboursement, TRI, prix maximum pour un TRI visé |
| Sensibilités | Quatre tables croisées, en formules |
| Contrôles | Cohérence du modèle, points de jugement, rapprochement avec le moteur Python |

Conventions de couleur : bleu pour un chiffre saisi, noir pour une formule, vert pour un lien vers un autre onglet.

## Installation

Python 3.11 ou plus récent.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[marche,dev]"
```

LibreOffice (gratuit) est facultatif : s'il est installé, Talanton s'en sert pour recalculer le classeur et vérifier qu'Excel et Python trouvent les mêmes chiffres. Sans lui, Excel calcule tout à l'ouverture et l'onglet Contrôles fait la même vérification.

## Utilisation

Rejouer l'exemple, sans réseau, à partir des données enregistrées dans le dépôt :

```powershell
.\.venv\Scripts\python.exe -m talanton run MAT --pairs HAS,FNKO,JAKK,YETI,GOLF `
    --cache exemples\cache --hors-ligne --ajustements exemples\retraitements\MAT.toml
```

Sur une autre société, en ligne. La SEC demande de s'identifier (nom et e-mail) :

```powershell
$env:TALANTON_CONTACT = "Prénom Nom prenom.nom@exemple.com"
.\.venv\Scripts\python.exe -m talanton run GIS --pairs CPB,CAG,SJM,KHC,HRL
```

Options : `--ajustements fichier.toml` (retraitements d'analyste), `--hypotheses fichier.toml` (remplace des hypothèses par défaut), `--sortie dossier`, `--sans-recalcul`, `--hors-ligne`.

### Les deux fichiers de l'analyste

Les décisions de jugement ne sont pas dans le code : elles vivent dans deux fichiers texte, versionnés avec le projet.

`retraitements/MAT.toml` corrige ou complète les comptes publiés, chaque ligne avec sa source :

```toml
[capex]
source = "10-K Mattel, tableau de flux (deux lignes d'investissement)"
"2025-12-31" = 181.992

[ebitda]
source = "Communiqué du T3 2026 : 88 M$ de remboursements de droits de douane"
"LTM" = -88.0
```

Un fichier d'hypothèses remplace les valeurs par défaut (un nombre, ou une liste de six valeurs pour une hypothèse annuelle) :

```toml
marge_ebitda = [0.115, 0.12, 0.125, 0.13, 0.13, 0.13]
prime_acquisition = 0.35
levier = 4.5
```

## Comment c'est construit

```
talanton/
├── collecte/        comptes (SEC EDGAR) et marché (Yahoo Finance), avec cache local
├── retraitement/    faits bruts -> états au format banque, LTM, ajustements d'analyste
├── modele/          hypothèses par défaut et projection des trois états
├── valorisation/    DCF, comparables, LBO, sensibilités
├── excel/           écriture du classeur et de ses formules
├── controles/       vérifications et rapprochement Python / Excel
├── moteur.py        assemblage, en Python pur
└── cli.py           ligne de commande
tests/               46 tests, sans réseau
exemples/            données enregistrées, ajustements Mattel, classeur produit
```

Le principe de fiabilité : le modèle existe deux fois. Le moteur Python calcule chaque chiffre sans Excel ; le classeur les recalcule avec ses formules. Les tests exigent que les deux coïncident à 0,0001 % près, y compris après avoir modifié une vingtaine d'hypothèses.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Méthodes, en bref

- **Douze derniers mois (LTM)** : dernier exercice + cumul de l'exercice en cours - même cumul un an plus tôt.
- **EBITDA ajusté** : résultat opérationnel + amortissements + dépréciations d'actifs + ajustements d'analyste.
- **Projections** : la première année part du rythme et de la marge des douze derniers mois, puis converge vers 2 % de croissance et vers la marge moyenne de trois exercices.
- **DCF** : flux disponibles actualisés au WACC (MEDAF, bêta ajusté de Blume), convention de milieu d'année, première année proratisée, valeur terminale par croissance perpétuelle et par multiple de sortie.
- **Comparables** : VE/CA, VE/EBITDA, VE/EBIT, PER sur douze mois glissants ; les multiples négatifs ou supérieurs à 40x sont écartés.
- **LBO** : rachat avec prime à la fin de l'exercice en cours, une tranche de dette, remboursement par la trésorerie excédentaire, revente cinq ans plus tard au multiple d'entrée. Le prix maximum pour un TRI visé est calculé par une formule exacte.

## Limites connues de la version 0.1

- Sociétés déposant leurs comptes à la SEC en US GAAP uniquement (pas encore les sociétés européennes).
- Banques, assureurs et foncières non couverts.
- Les comparables sont choisis par l'utilisateur ; pas de transactions comparables.
- Une seule tranche de dette dans le LBO, frais passés en charge, pas de management package.
- Dilution non calculée (champ à renseigner), dettes de location laissées hors dette nette.
- Les exercices sont étiquetés par l'année de leur date de clôture.
- Le téléchargement en ligne (SEC, Yahoo Finance) est testé avec un réseau simulé ; l'exemple fourni tourne sur des données réelles enregistrées le 10 novembre 2026.

## Sources de données

- Comptes : SEC EDGAR, API `companyfacts` ([exemple pour Mattel](https://data.sec.gov/api/xbrl/companyfacts/CIK0000063276.json)). Gratuite, sans clé, 10 requêtes par seconde au plus, identification obligatoire.
- Cours, bêta, taux à 10 ans : Yahoo Finance via `yfinance`, pour un usage personnel.
- Prime de risque du marché : [A. Damodaran, NYU Stern](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm), valeur du 1er novembre 2026 inscrite dans `talanton/modele/hypotheses.py`, à mettre à jour.

## English summary

Talanton turns a US-listed ticker into a full M&A / LBO valuation model in Excel with live formulas: restated financials from SEC EDGAR, a three-statement projection, DCF, trading comparables, an LBO with debt schedule and sponsor returns, sensitivity tables and a football field. A pure-Python engine computes every figure independently and the test suite checks that Excel and Python agree. Code, labels and documentation are in French.
