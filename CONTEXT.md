# TW Stock Portfolio

Tracks a user's Taiwan-market stock and ETF holdings, their market value, and projected dividend income.

## Language

**Holding**:
A stock or ETF the user owns: the security, how many shares, and what was paid for them.
_Avoid_: position

**Market Quote**:
The latest known trading price for a security.
_Avoid_: price, quote data

**Holding View**:
A Holding combined with its latest Market Quote: market value, profit, and return rate alongside the original cost.
_Avoid_: portfolio row, holding summary

**Selection**:
The one Holding the user has currently picked in the holdings table, which determines what's shown in the dividend and AI research areas.
_Avoid_: current holding, active row

**Holding View State**:
The current cache of Holding Views together with the Selection.
_Avoid_: view cache, selected holding dict
