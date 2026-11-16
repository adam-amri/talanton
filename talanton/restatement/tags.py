"""Mapping between the lines of the model and XBRL tags (US GAAP).

Companies do not all tag the same way. For each line, tags are tried in order
and the first one available for the period is kept. The order is an analyst's
choice, documented here.
"""

# Tags used to locate the published fiscal years and quarters.
ANCHORS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
    "NetIncomeLoss", "OperatingIncomeLoss",
)

# --- flows (income statement, cash-flow statement): first tag available ---
FLOWS = {
    # "Revenues" is sometimes a total before intersegment eliminations (Hasbro):
    # the ASC 606 tag therefore comes first.
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"),
    "gross_profit": ("GrossProfit",),
    "ebit": ("OperatingIncomeLoss",),
    "da": ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet"),
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"),
    "interest_income": ("InvestmentIncomeInterest", "InterestIncomeOther"),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
    "income_tax": ("IncomeTaxExpenseBenefit",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "sbc": ("ShareBasedCompensation",),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
    "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
}

# D&A: when there is no total, sum of the two components.
DA_COMPONENTS = ("Depreciation", "AmortizationOfIntangibleAssets")

# Capex: when there is no total, sum of the partial lines (flagged as incomplete).
CAPEX_PARTIAL = ("PaymentsToAcquireOtherPropertyPlantAndEquipment",
                 "PaymentsToAcquireMachineryAndEquipment")

# Asset impairments, added back to EBITDA: non-cash and non-recurring charge.
# The larger of the two amounts (aggregate tag / sum of detailed tags) is kept,
# so that nothing is counted twice.
IMPAIRMENTS_AGGREGATE = ("AssetImpairmentCharges", "GoodwillAndIntangibleAssetImpairment")
IMPAIRMENTS_DETAIL = (
    "GoodwillImpairmentLoss", "ImpairmentOfIntangibleAssetsExcludingGoodwill",
    "ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill",
    "ImpairmentOfIntangibleAssetsFinitelived", "ImpairmentOfLongLivedAssetsHeldForUse",
)

# --- balance sheet (instants): first tag available ---
BALANCE = {
    "cash_equivalents": ("CashAndCashEquivalentsAtCarryingValue",
                         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"),
    "short_term_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
    "receivables": ("AccountsReceivableNetCurrent",),
    "inventory": ("InventoryNet",),
    "current_assets": ("AssetsCurrent",),
    "ppe": ("PropertyPlantAndEquipmentNet",),
    "intangibles": ("IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"),
    "goodwill": ("Goodwill",),
    "total_assets": ("Assets",),
    "payables": ("AccountsPayableCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
    "short_term_debt": ("DebtCurrent", "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
    "total_debt_fallback": ("LongTermDebt",),
    "equity_parent": ("StockholdersEquity",),
    "equity_total": ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",),
    "total_liabilities_equity": ("LiabilitiesAndStockholdersEquity",),
}

# Short-term borrowings added to `short_term_debt` (unless "DebtCurrent" already includes them).
SHORT_TERM_DEBT_EXTRAS = ("ShortTermBorrowings", "CommercialPaper", "LinesOfCreditCurrent")

# Non-controlling interests: sum of the tags present.
MINORITIES = ("MinorityInterest", "RedeemableNoncontrollingInterestEquityCarryingAmount")

COVER_PAGE_SHARES = "EntityCommonStockSharesOutstanding"      # "dei" namespace
DILUTED_SHARES = "WeightedAverageNumberOfDilutedSharesOutstanding"

# Dilutive securities, for the treasury stock method (published once a year, in the 10-K).
OPTIONS_OUTSTANDING = "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber"
OPTIONS_STRIKE = "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice"
RSUS_NONVESTED = "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber"

# Operating lease liabilities: total, or current + non-current.
LEASES_TOTAL = ("OperatingLeaseLiability",)
LEASES_PARTS = ("OperatingLeaseLiabilityCurrent", "OperatingLeaseLiabilityNoncurrent")
