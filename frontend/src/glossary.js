// Plain-English definitions shown by <Tip term="..." />.
export const GLOSSARY = {
  // Stock basics
  market_cap: 'Market cap: share price × shares outstanding — the total value the market puts on the company.',
  pe: 'P/E ratio: price ÷ the last 12 months of earnings per share. Roughly how many years of today\'s profit you are paying for. Compare with peers, not in isolation.',
  eps: 'EPS: earnings per share over the last 12 months.',
  beta: 'Beta: how much the stock tends to move vs the S&P 500. 1.0 = same as the market, 1.5 = ~50% bigger swings, below 1 = calmer.',
  sma: 'Moving average: the average closing price over N days. Price above the 50D/200D average is generally an uptrend.',
  div_yield: 'Dividend yield: yearly dividends ÷ share price.',

  // Day trading
  gap: 'Gap: how far today opened above/below yesterday\'s close. Big gaps usually come from news or earnings.',
  rvol: 'Relative volume: today\'s volume vs what is normal by this time of day. 2× = twice as busy as usual — a sign something is going on.',
  levels: 'Key intraday levels. PDH/PDL/PDC = previous day high/low/close. PMH/PML = pre-market high/low. OR15/OR30 = high and low of the first 15/30 minutes. Traders watch these for breakouts and reversals.',

  // Options
  iv: 'Implied volatility (IV): how big a move option prices are bracing for, as a yearly %. Higher IV = more expensive options.',
  iv_rank: 'IV rank: today\'s IV vs the past year. 0 = cheapest, 100 = most expensive. High favours selling options, low favours buying them.',
  expected_move: 'Expected move: the ± range options are pricing by expiry. The stock ends inside it roughly 2 times out of 3.',
  delta: 'Delta: how much the option price moves per $1 in the stock. Also a rough chance the option finishes in-the-money (0.20 ≈ 20%).',
  open_interest: 'Open interest (OI): number of contracts currently open. Higher OI usually means tighter bid/ask spreads and better fills.',
  pc_ratio: 'Put/call ratio: put activity ÷ call activity. Above 1 = more puts (bearish bets or hedging). Below ~0.6 = call-heavy (bullish).',
  call_wall: 'Call wall: the strike with the most call open interest. Often acts like resistance because of dealer hedging.',
  put_wall: 'Put wall: the strike with the most put open interest. Often acts like support.',
  gamma_flip: 'Gamma flip: the price where options dealers\' hedging changes direction. Above it they tend to dampen moves (sell rallies, buy dips); below it moves can accelerate.',
  dealer_gamma: 'Dealer gamma: positive = dealer hedging tends to calm price moves; negative = it tends to amplify them. Shown as $ hedged per 1% move.',
  max_pain: 'Max pain: the expiry price at which option buyers collectively lose the most. Price sometimes drifts toward it into expiry — a weak magnet, not a target.',
  unusual: 'Unusual activity: today\'s volume is bigger than existing open interest, so new positions are likely being opened. "At ask" suggests a buyer, "at bid" a seller.',
  return_on_risk: 'Return on risk: credit received ÷ the most you can lose. Higher looks better but usually means a lower chance of profit.',
  pop: 'Chance of profit: a model estimate (from option prices) that the trade makes any money at expiry. Not a guarantee — big moves happen more often than models assume.',
  natural_credit: 'Natural credit: what you would get filling instantly at the worst prices (sell at bid, buy at ask). Aim for a limit between natural and mid.',

  // Setups
  rs_rating: 'Relative strength (1–99): how this stock performed over the past year vs scanned S&P 500 and Nasdaq-100 stocks, weighted toward the last 3 months. 80+ = a market leader.',
  rsi: 'RSI (0–100): momentum gauge. Above 70 = stretched after a run-up, below 30 = washed out after a drop, 40–60 = neutral.',
  rvol_daily: 'Relative volume: today\'s volume vs the 50-day average. 1.5×+ means unusually heavy trading.',
  atr_stop: 'Suggested stop 1.5× ATR below price and target 3× ATR above (2:1 reward/risk). ATR is the stock\'s average daily range, so stops scale with how much it normally moves.',

  // Short interest / smart money
  short_interest: 'Short interest: shares sold short and not yet bought back, reported by FINRA twice a month.',
  days_to_cover: 'Days to cover: shares short ÷ average daily volume. 7+ days means shorts would struggle to exit quickly — short-squeeze risk if good news hits.',

  // Backtests
  win_rate: 'Win rate: % of trades that made money. Meaningless alone — a 40% win rate can be very profitable if winners are bigger than losers.',
  profit_factor: 'Profit factor: total gains ÷ total losses. Above 1 = profitable, 1.5+ = good, below 1 = loses money.',
  max_drawdown: 'Max drawdown: the biggest peak-to-trough drop in the equity curve — the worst pain you would have sat through.',
};
