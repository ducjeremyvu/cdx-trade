Options basics (learning only)

Scope
- Educational reference only. No options trading execution in V0.
- Paper data is 15-minute delayed, so avoid intraday options decisions.

Core concepts
- Call: right to buy the underlying at a strike price by expiration.
- Put: right to sell the underlying at a strike price by expiration.
- Premium: the price paid/received for the contract.
- Expiration: last day the option is valid (time decay accelerates).

Greeks (intuition)
- Delta: how much option price changes per $1 move in the underlying.
- Gamma: how delta changes as price moves.
- Theta: time decay; options lose value as expiration approaches.
- Vega: sensitivity to changes in implied volatility.

Risks to respect
- Options can go to zero quickly.
- Spreads and assignment add complexity.
- Low liquidity = wide bid/ask spreads.

If/when we explore options (future V1)
- Use only defined-risk strategies (e.g., single-leg long options).
- Stick to 1 contract max; no scaling.
- Require a documented thesis, stop, and time-based exit.
- Paper trade only until review stats show consistency.
