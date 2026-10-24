"""Provider-reported attempt usage, not a billing ledger."""
from collections.abc import Sequence
from decimal import Decimal

from .contracts import (BudgetDecision, CostEstimate, PriceTable, Settings, Usage,
                        UsageLedger)


def append_usage(ledger: UsageLedger, entry: Usage) -> UsageLedger:
    return UsageLedger(entries=[*ledger.entries, entry],
                       known_input=ledger.known_input + (entry.input_tokens or 0),
                       known_output=ledger.known_output + (entry.output_tokens or 0),
                       complete=ledger.complete and entry.complete)


def may_dispatch(ledger: UsageLedger, config: Settings) -> BudgetDecision:
    if config.max_tokens_budget is None:
        return BudgetDecision(allowed=True, reason="no_budget")
    if not ledger.complete:
        return BudgetDecision(allowed=False, reason="unknown_usage")
    if ledger.known_input + ledger.known_output >= config.max_tokens_budget:
        return BudgetDecision(allowed=False, reason="soft_budget_reached")
    return BudgetDecision(allowed=True, reason="under_budget")


def estimate_cost(ledger: UsageLedger, rates: PriceTable | None) -> CostEstimate:
    if rates is None or not ledger.complete:
        return CostEstimate(reason="unknown_rates" if rates is None else "incomplete_usage")
    return CostEstimate(amount=(Decimal(ledger.known_input) * rates.input_per_million
                                + Decimal(ledger.known_output) * rates.output_per_million)
                        / Decimal(1000000), currency=rates.currency, as_of=rates.as_of,
                        complete=True)
