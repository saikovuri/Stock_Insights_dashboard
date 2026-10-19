// Multi-leg option structures; mirrors backend/spreads.py. A leg is
// { position: 'long'|'short', option_type: 'call'|'put', strike, expiry, ratio, premium (per share) }.

const leg = (position, option_type, ratio, hint) => ({ position, option_type, ratio, hint });

export const STRUCTURES = {
  bull_call: { label: 'Bull call', family: 'vertical', style: 'debit', hint: 'Pay a debit; profits if the stock rises above the lower strike.',
    legs: [leg('long', 'call', 1, 'lower strike'), leg('short', 'call', 1, 'higher strike')] },
  bull_put: { label: 'Bull put', family: 'vertical', style: 'credit', hint: 'Collect a credit; keeps it if the stock stays above the higher strike.',
    legs: [leg('long', 'put', 1, 'lower strike'), leg('short', 'put', 1, 'higher strike')] },
  bear_call: { label: 'Bear call', family: 'vertical', style: 'credit', hint: 'Collect a credit; keeps it if the stock stays below the lower strike.',
    legs: [leg('short', 'call', 1, 'lower strike'), leg('long', 'call', 1, 'higher strike')] },
  bear_put: { label: 'Bear put', family: 'vertical', style: 'debit', hint: 'Pay a debit; profits if the stock falls below the higher strike.',
    legs: [leg('short', 'put', 1, 'lower strike'), leg('long', 'put', 1, 'higher strike')] },
  iron_condor: { label: 'Iron condor', family: 'iron', style: 'credit', hint: 'Collect a credit; keeps it if the stock stays between the two sold strikes.',
    legs: [leg('long', 'put', 1, 'lowest strike'), leg('short', 'put', 1, 'second strike'), leg('short', 'call', 1, 'third strike'), leg('long', 'call', 1, 'highest strike')] },
  iron_butterfly: { label: 'Iron butterfly', family: 'iron', style: 'credit', hint: 'Sell a put and a call at the same middle strike; most profit if the stock pins it.',
    legs: [leg('long', 'put', 1, 'lowest strike'), leg('short', 'put', 1, 'middle strike'), leg('short', 'call', 1, 'same middle strike'), leg('long', 'call', 1, 'highest strike')] },
  call_butterfly: { label: 'Call butterfly', family: 'butterfly', style: null, hint: 'Buy 1-sell 2-buy 1; most profit if the stock finishes at the middle strike.',
    legs: [leg('long', 'call', 1, 'lowest strike'), leg('short', 'call', 2, 'middle strike'), leg('long', 'call', 1, 'highest strike')] },
  put_butterfly: { label: 'Put butterfly', family: 'butterfly', style: null, hint: 'Buy 1-sell 2-buy 1; most profit if the stock finishes at the middle strike.',
    legs: [leg('long', 'put', 1, 'lowest strike'), leg('short', 'put', 2, 'middle strike'), leg('long', 'put', 1, 'highest strike')] },
  call_calendar: { label: 'Call calendar', family: 'calendar', style: 'debit', multi: true, hint: 'Sell a nearer call and buy a later one at the same strike; gains as the near one decays.',
    legs: [leg('short', 'call', 1, 'nearer expiry'), leg('long', 'call', 1, 'later expiry, same strike')] },
  put_calendar: { label: 'Put calendar', family: 'calendar', style: 'debit', multi: true, hint: 'Sell a nearer put and buy a later one at the same strike; gains as the near one decays.',
    legs: [leg('short', 'put', 1, 'nearer expiry'), leg('long', 'put', 1, 'later expiry, same strike')] },
  call_diagonal: { label: 'Call diagonal', family: 'calendar', style: 'debit', multi: true, hint: 'Sell a nearer call and buy a later one at a different strike.',
    legs: [leg('short', 'call', 1, 'nearer expiry'), leg('long', 'call', 1, 'later expiry')] },
  put_diagonal: { label: 'Put diagonal', family: 'calendar', style: 'debit', multi: true, hint: 'Sell a nearer put and buy a later one at a different strike.',
    legs: [leg('short', 'put', 1, 'nearer expiry'), leg('long', 'put', 1, 'later expiry')] },
};

const SUPPORTED = 'Supported: verticals, iron condors and iron butterflies, 1-2-1 butterflies, and calendars or diagonals that sell the nearer expiry and buy the later one.';
const sign = l => (l.position === 'long' ? 1 : -1);
const intrinsic = (l, price) => (l.option_type === 'call' ? Math.max(price - l.strike, 0) : Math.max(l.strike - price, 0));
const fmt = value => `$${Number(value)}`;
const round = (value, places = 2) => Math.round(value * 10 ** places) / 10 ** places;

export const legName = l => `${l.position === 'long' ? 'Buy' : 'Sell'} ${l.ratio} ${l.option_type}${l.ratio > 1 ? 's' : ''}`;
export const structureName = s => (s.family === 'vertical' ? `${s.label} spread` : s.label);

export function classify(legs) {
  if (legs.length < 2 || legs.length > 4) throw new Error(`A structure needs 2 to 4 legs. ${SUPPORTED}`);
  if (new Set(legs.map(l => `${l.position}|${l.option_type}|${l.strike}|${l.expiry}`)).size !== legs.length)
    throw new Error('Two legs are the same contract; combine them into one leg');
  const expiries = new Set(legs.map(l => l.expiry));
  const types = new Set(legs.map(l => l.option_type));
  if (legs.length === 2) {
    const long = legs.find(l => l.position === 'long'), short = legs.find(l => l.position === 'short');
    if (!long || !short || types.size !== 1 || long.ratio !== short.ratio)
      throw new Error(`A two-leg structure buys one option and sells another of the same type, one for one. ${SUPPORTED}`);
    if (expiries.size === 1) {
      if (long.strike === short.strike) throw new Error('A vertical spread needs two different strikes');
      return `${long.strike < short.strike ? 'bull' : 'bear'}_${long.option_type}`;
    }
    if (long.expiry < short.expiry) throw new Error('A calendar or diagonal sells the nearer expiry and buys the later one');
    return `${long.option_type}_${long.strike === short.strike ? 'calendar' : 'diagonal'}`;
  }
  if (expiries.size !== 1) throw new Error(`Butterflies and iron condors use one expiry for every leg. ${SUPPORTED}`);
  if (legs.length === 3) {
    const [low, mid, high] = [...legs].sort((a, b) => a.strike - b.strike);
    if (types.size === 1 && low.position === 'long' && high.position === 'long' && mid.position === 'short'
      && low.strike < mid.strike && mid.strike < high.strike && low.ratio === high.ratio && mid.ratio === 2 * low.ratio)
      return `${mid.option_type}_butterfly`;
    throw new Error(`A butterfly buys one low strike, sells two middle strikes and buys one high strike. ${SUPPORTED}`);
  }
  const puts = legs.filter(l => l.option_type === 'put').sort((a, b) => a.strike - b.strike);
  const calls = legs.filter(l => l.option_type === 'call').sort((a, b) => a.strike - b.strike);
  if (puts.length === 2 && calls.length === 2 && new Set(legs.map(l => l.ratio)).size === 1
    && [puts[0].position, puts[1].position, calls[0].position, calls[1].position].join() === 'long,short,short,long'
    && puts[0].strike < puts[1].strike && puts[1].strike <= calls[0].strike && calls[0].strike < calls[1].strike)
    return puts[1].strike === calls[0].strike ? 'iron_butterfly' : 'iron_condor';
  throw new Error(`Four legs must form an iron condor: buy a low put, sell a higher put, sell a call at or above it and buy a higher call. ${SUPPORTED}`);
}

function strikesLabel(legs) {
  if (new Set(legs.map(l => l.expiry)).size === 1) return [...new Set(legs.map(l => l.strike))].sort((a, b) => a - b).map(fmt).join('/');
  const [near, far] = [...legs].sort((a, b) => a.expiry.localeCompare(b.expiry));
  return `${fmt(near.strike)} ${near.expiry} / ${fmt(far.strike)} ${far.expiry}`;
}

/** Net debit/credit, payoff limits at expiry, breakevens and collateral for `units` structures; throws on an unsupported shape. */
export function describe(legs, units = 1) {
  const kind = classify(legs);
  const meta = STRUCTURES[kind];
  const net = legs.reduce((sum, l) => sum + sign(l) * l.ratio * l.premium, 0);
  const multi = new Set(legs.map(l => l.expiry)).size > 1;
  const value = price => legs.reduce((sum, l) => sum + sign(l) * l.ratio * intrinsic(l, price), 0);
  const strikes = [...new Set(legs.map(l => l.strike))].sort((a, b) => a - b);
  const points = [0, ...strikes, strikes.at(-1) * 2 + 1];
  const values = points.map(p => value(p) - net);
  const scale = 100 * units;
  const breakevens = [];
  if (!multi) points.slice(0, -1).forEach((p0, i) => {
    const [v0, p1, v1] = [values[i], points[i + 1], values[i + 1]];
    if (v0 === 0 && p0 > 0) breakevens.push(round(p0, 4));
    else if (v0 * v1 < 0) breakevens.push(round(p0 + (p1 - p0) * (-v0) / (v1 - v0), 4));
  });
  return { kind, label: meta.label, family: meta.family, style: net > 0 ? 'debit' : 'credit', net: round(Math.abs(net), 4),
    multi, strikes: strikesLabel(legs), breakevens,
    maxLoss: round(Math.max(-Math.min(...values), 0) * scale), maxProfit: multi ? null : round(Math.max(...values) * scale),
    collateral: round(Math.max(-Math.min(...points.map(value)), 0) * scale) };
}

/** describe() plus the opening checks, as { error } instead of throwing; null until every number is filled in. */
export function previewStructure(legs, units, expectKind) {
  const ready = legs.every(l => [l.strike, l.premium].every(v => v !== '' && v != null && Number.isFinite(Number(v))) && Number(l.strike) > 0
    && Number(l.premium) >= 0 && l.expiry);
  if (!ready || !(Number(units) > 0)) return null;
  const parsed = legs.map(l => ({ ...l, strike: Number(l.strike), premium: Number(l.premium), ratio: Number(l.ratio) }));
  try {
    const info = describe(parsed, Number(units));
    const expected = STRUCTURES[info.kind].style;
    if (expectKind && expectKind !== info.kind)
      return { error: `These strikes make a ${info.label.toLowerCase()}, not a ${STRUCTURES[expectKind].label.toLowerCase()}; check which strike each leg uses.` };
    if (info.net === 0) return { error: 'The fills net to zero; check the prices.' };
    if (expected && info.style !== expected) return { error: `A ${info.label.toLowerCase()} is opened for a ${expected}; check the prices.` };
    if (info.maxLoss <= 0) return { error: "At these prices the trade can't lose money; check the fills." };
    if (info.maxProfit != null && info.maxProfit <= 0) return { error: 'At these prices it cannot make money; check the fills.' };
    return info;
  } catch (error) { return { error: error.message }; }
}

/** Blank legs for a structure template, sharing an expiry unless it is a calendar/diagonal. */
export const templateLegs = kind => STRUCTURES[kind].legs.map(l => ({ ...l, strike: '', expiry: '', premium: '', close: '' }));
