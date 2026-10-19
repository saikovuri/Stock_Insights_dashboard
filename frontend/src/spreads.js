// Two-leg vertical spreads. Bull spreads buy the lower strike and sell the higher; bear spreads the reverse.
export const SPREAD_KINDS = {
  bull_call: { label: 'Bull call', type: 'call', style: 'debit', hint: 'Pay a debit; profits if the stock rises above the lower strike.' },
  bull_put: { label: 'Bull put', type: 'put', style: 'credit', hint: 'Collect a credit; keeps it if the stock stays above the higher strike.' },
  bear_call: { label: 'Bear call', type: 'call', style: 'credit', hint: 'Collect a credit; keeps it if the stock stays below the lower strike.' },
  bear_put: { label: 'Bear put', type: 'put', style: 'debit', hint: 'Pay a debit; profits if the stock falls below the higher strike.' },
};

const positive = value => value !== '' && value != null && Number.isFinite(Number(value)) && Number(value) > 0;
const nonNegative = value => value !== '' && value != null && Number.isFinite(Number(value)) && Number(value) >= 0;

/** Which strike each leg uses: bull spreads buy the lower strike, bear spreads buy the higher one. */
export function spreadLegs(kind, lower, upper) {
  return kind.startsWith('bull') ? { long_strike: lower, short_strike: upper } : { long_strike: upper, short_strike: lower };
}

/** Net debit/credit per share and the payoff limits at expiry, or an error explaining what is wrong. */
export function spreadPreview({ kind, lower, upper, longPremium, shortPremium, contracts = 1 }) {
  const meta = SPREAD_KINDS[kind];
  if (!meta || !positive(lower) || !positive(upper) || !nonNegative(longPremium) || !nonNegative(shortPremium)) return null;
  const low = Number(lower), high = Number(upper), qty = Number(contracts) || 1;
  if (low >= high) return { error: 'The lower strike must be below the upper strike.' };
  const width = high - low;
  const net = meta.style === 'credit' ? Number(shortPremium) - Number(longPremium) : Number(longPremium) - Number(shortPremium);
  if (net <= 0) return { error: meta.style === 'credit' ? 'A credit spread should collect more for the short leg than it pays for the long leg.'
    : 'A debit spread should cost more for the long leg than it collects for the short leg.' };
  if (net >= width) return { error: `The net ${meta.style} of $${net.toFixed(2)} is not below the $${width.toFixed(2)} strike width; check the prices.` };
  const [profit, loss] = meta.style === 'credit' ? [net, width - net] : [width - net, net];
  const breakeven = (kind === 'bull_put' || kind === 'bear_put') ? high - net : low + net;
  return { net, width, style: meta.style, maxProfit: profit * 100 * qty, maxLoss: loss * 100 * qty, breakeven,
    collateral: meta.style === 'credit' ? width * 100 * qty : 0 };
}

export const spreadName = spread => `${spread.label} $${spread.long_strike}/$${spread.short_strike}`;
