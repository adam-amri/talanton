"""Correspondance entre les postes du modèle et les balises XBRL (US GAAP).

Les sociétés ne balisent pas toutes de la même façon. Pour chaque poste, on
essaie les balises dans l'ordre et on garde la première disponible pour la
période. L'ordre est un choix d'analyste, documenté ici.
"""

# Balises qui servent à repérer les exercices et les trimestres publiés.
REPERES = (
    "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
    "NetIncomeLoss", "OperatingIncomeLoss",
)

# --- flux (compte de résultat, tableau de flux) : première balise disponible ---
FLUX = {
    # « Revenues » désigne parfois un total avant éliminations intersecteurs
    # (cas de Hasbro) : la balise IFRS 15 / ASC 606 passe donc en premier.
    "ca": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"),
    "marge_brute": ("GrossProfit",),
    "ebit": ("OperatingIncomeLoss",),
    "da": ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet"),
    "interets": ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"),
    "produits_fin": ("InvestmentIncomeInterest", "InterestIncomeOther"),
    "rai": ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
    "impot": ("IncomeTaxExpenseBenefit",),
    "rn": ("NetIncomeLoss", "ProfitLoss"),
    "sbc": ("ShareBasedCompensation",),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "rachats": ("PaymentsForRepurchaseOfCommonStock",),
    "dividendes": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
}

# D&A : à défaut de total, somme des deux composantes.
DA_COMPOSANTES = ("Depreciation", "AmortizationOfIntangibleAssets")

# Capex : à défaut de total, somme des lignes partielles (signalée comme incomplète).
CAPEX_PARTIELLES = ("PaymentsToAcquireOtherPropertyPlantAndEquipment",
                    "PaymentsToAcquireMachineryAndEquipment")

# Dépréciations d'actifs (impairments), réintégrées à l'EBITDA : charge sans
# décaissement et non récurrente. On retient le plus grand des deux montants
# (balise agrégée / somme des balises détaillées) pour ne pas compter deux fois.
DEPRECIATIONS_AGREGEES = ("AssetImpairmentCharges", "GoodwillAndIntangibleAssetImpairment")
DEPRECIATIONS_DETAIL = (
    "GoodwillImpairmentLoss", "ImpairmentOfIntangibleAssetsExcludingGoodwill",
    "ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill",
    "ImpairmentOfIntangibleAssetsFinitelived", "ImpairmentOfLongLivedAssetsHeldForUse",
)

# --- bilan (instantanés) : première balise disponible ---
BILAN = {
    "caisse": ("CashAndCashEquivalentsAtCarryingValue",
               "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"),
    "placements": ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
    "creances": ("AccountsReceivableNetCurrent",),
    "stocks": ("InventoryNet",),
    "actif_courant": ("AssetsCurrent",),
    "immo_corporelles": ("PropertyPlantAndEquipmentNet",),
    "immo_incorporelles": ("IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"),
    "goodwill": ("Goodwill",),
    "total_actif": ("Assets",),
    "fournisseurs": ("AccountsPayableCurrent",),
    "passif_courant": ("LiabilitiesCurrent",),
    "dette_lt": ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
    "dette_ct": ("DebtCurrent", "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
    "dette_totale_secours": ("LongTermDebt",),
    "cp_groupe": ("StockholdersEquity",),
    "cp_total": ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",),
    "total_passif": ("LiabilitiesAndStockholdersEquity",),
}

# Dettes court terme qui s'ajoutent à `dette_ct` (sauf si « DebtCurrent » les contient déjà).
DETTE_CT_COMPLEMENTS = ("ShortTermBorrowings", "CommercialPaper", "LinesOfCreditCurrent")

# Intérêts minoritaires : somme des balises présentes.
MINORITAIRES = ("MinorityInterest", "RedeemableNoncontrollingInterestEquityCarryingAmount")

ACTIONS_COUVERTURE = "EntityCommonStockSharesOutstanding"      # espace « dei »
ACTIONS_DILUEES = "WeightedAverageNumberOfDilutedSharesOutstanding"
