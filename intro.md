# StockPilot: Views, Rules, and Decision Guide

This guide describes the implementation as inspected on October 5, 2026. It explains what each workspace does, how candidates are selected, and what the displayed numbers mean. Code references identify the implementation behind the descriptions. These are the application's current rules, not a claim that the thresholds are optimal or that a strategy has a proven trading edge.

## Contents

- [Main navigation](#main-navigation)
- [Profiles and Dashboard](#trading-profiles-and-dashboard)
- [Setup scanner](#ideas-navigation-and-setup-scanner)
- [Wheel qualification and capital planning](#wheel-candidate-qualification)
- [Shared options rules](#shared-options-rules)
- [Volatility](#options-hub-volatility)
- [Income / Sell premium](#options-hub-income--sell-premium)
- [Directional](#options-hub-directional)
- [Wheel assessment and management](#wheel-ask-assigned-calls-and-roll--repair)
- [In Play and Reddit attention](#ideas-in-play)
- [Flow and unusual options](#options-flow-and-unusual-options)
- [Insider buying and Superinvestors](#ideas-insider-buying-and-superinvestors)
- [Macro and prediction markets](#ideas-macro-calendar-and-prediction-markets)
- [Strategy Tester](#ideas-strategy-tester)
- [Paper options track record](#ideas-options-track-record)
- [Watchlist](#watchlist)
- [Holdings](#portfolio-holdings)
- [Portfolio Risk](#portfolio-portfolio-risk)
- [Income & Performance](#portfolio-income--performance)
- [Long-term criteria](#fundamentals-long-term-criteria)
- [Journal and planning tools](#journal-and-trade-planning)
- [Charts and remaining controls](#chart-and-panel-controls)
- [Alerts and notifications](#alerts-notifications-and-briefings)
- [News and AI interpretation](#news-and-ai-interpretation)
- [Data sources and scope](#data-sources-scope-and-rule-intent)

## Reading the App

Keep four different concepts separate:

1. **Qualification:** a backend rule determines whether an instrument becomes a candidate.
2. **Display filtering:** a control determines which returned candidates are visible.
3. **Sizing and eligibility:** account cash, holdings, earnings, quotes, and risk constraints determine whether contracts can be allocated.
4. **Ranking and commentary:** a score or AI explanation orders or discusses candidates; it does not override hard eligibility checks.

An absent candidate does not necessarily mean a bad investment. It can mean missing data, no suitable expiry, an illiquid contract, an earnings conflict, a stale scan, or a portfolio constraint. A displayed candidate is not an executable order. Quotes, premiums, probabilities, and annualizations are estimates.

## Main Navigation

| Workspace | Purpose |
| --- | --- |
| Dashboard | Market overview before selecting a ticker; detailed stock research after selecting one. |
| Ideas | Cross-stock discovery, Wheel candidates, options activity, ownership events, macro events, strategy experiments, and paper tracking. |
| Watchlist | Follow a user-selected list of symbols, compare quote/technical columns, and manage alerts. |
| Portfolio | Recorded holdings and options, account risks, income/performance, and the account ledger. |
| Journal | Separate recorded trading history from manually written trade plans and reviews. |

The Dashboard has Overview, Analysis, Fundamentals, and News subtabs. The trading-style selector changes defaults, ordering, and visibility; it is not an account risk limit. Sign-in enables account-specific features. Theme controls affect appearance only. Older `#setups`, `#screener`, and `#tools` links route to Ideas, Watchlist, and Journal respectively.

Source: [frontend/src/App.jsx](frontend/src/App.jsx).

## Trading Profiles and Dashboard

### Trading-Style Defaults

| Profile | Initial chart | Dashboard tab order | Initially hidden cards | Options tab order |
| --- | --- | --- | --- | --- |
| Day trader | One day, five-minute bars | Overview, Analysis, News, Fundamentals | Thesis, long-term view, raw statements, ownership | Flow, Volatility, Directional, Income |
| Swing trader (default) | Six months, daily bars | Overview, Analysis, Fundamentals, News | Raw statements | Volatility, Flow, Directional, Income |
| Long-term investor | Five years, weekly bars | Overview, Fundamentals, News, Analysis | Relative strength | Income, Volatility |

The "show hidden cards" control reveals the remaining cards and options tabs. Profiles are stored locally and synchronized for signed-in users. They change presentation and AI context, not Wheel thresholds or portfolio concentration limits.

Source: [frontend/src/ProfileContext.jsx](frontend/src/ProfileContext.jsx).

### Dashboard Before Selecting a Stock

The landing dashboard presents market overview data, a compact economic calendar, and a daily briefing for signed-in users. The watchlist rail provides ticker shortcuts. Searching or selecting a ticker opens that stock's research; the Dashboard is not a broker order-entry screen.

### Overview Tab

| Panel | What it contains |
| --- | --- |
| Alerts | Deterministic warnings derived from the stock's metrics. These differ from saved notification alerts. |
| Key metrics | Price and daily change, market capitalization, valuation and other reported stock statistics. Missing provider fields are not proof of zero or absence. |
| AI Brief | Profile-aware narrative, cited headlines, bull/bear arguments, risks, catalysts, and technical context. AI interpretation may be wrong and is not the deterministic options eligibility engine. |
| Thesis | A signed-in user's investment thesis and subsequent reviews. Normally hidden for day traders. |
| Price chart | Price history, selectable range/bar interval, extended-hours toggle, and event overlays. The visible time horizon follows the selected profile until changed. |
| Price alerts | Save price/RSI conditions for account notifications; this is distinct from visually drawn chart levels. |

### Analysis Tab

The panel order is relative strength, Options Hub, short interest/smart money, analyst ratings, peer comparisons, and AI Chat. Relative strength is hidden initially for the long-term profile. The Options Hub's four views are Volatility, Income ("Sell premium"), Directional, and Flow & positioning; their rules are detailed below.

Relative strength is not RSI. The scanner's raw RS measure is `0.4 * 3-month return + 0.2 * 6-month return + 0.2 * 9-month return + 0.2 * 12-month return`, using approximately 63/126/189/252 trading bars. It converts this into a roughly 1-99 percentile rating within the available scan. Separate one-, three-, six-, and twelve-month comparisons show stock return minus SPY return, in percentage points. Sector rankings average member RS ratings. A ticker outside the current scan can be compared against its stored distribution; if no suitable distribution exists, its RS rating can be unavailable.

Analyst targets and recommendations are third-party opinions, not app-generated fair values. Short interest, institutional holdings and filings can lag market prices. A high short-interest value or high institutional ownership alone is not a buy/sell signal. AI Chat answers questions using available tools and account context; it does not authorize broker trades.

### Fundamentals Tab

The long-term view interprets growth, profitability, balance-sheet and valuation data; ownership shows holders; expandable raw statements contain Income Statement, Balance Sheet and Cash Flow views. These are reporting-period data, not intraday facts. Financial comparisons need consistent units, fiscal periods and accounting definitions. The long-term view's scoring and valuation rules are described in the criteria reference below.

### News Tab

Shows the selected ticker's articles and sentiment summaries. A sentiment score reflects text classification, not a forecast of stock returns. Distinguish article publication time, retrieval time, and the market event itself. Social mention counts are kept separately in Ideas > In play; they are not silently presented as verified news.

## Ideas: Navigation and Setup Scanner

The nine tabs are **In play**, **Setups**, **Wheel**, **Unusual options**, **Insider buying**, **Superinvestors**, **Macro calendar**, **Strategy tester**, and **Options track record**. The selected Ideas tab is remembered for the session; absent a saved choice, day traders start at In play and other profiles at Setups.

### Setups: Universe and Trend

The standard universe is the current S&P 500 constituent list, cached for seven days. If the list cannot be refreshed, the app uses the cached list; without a cache, it falls back to a small predefined set of ten large stocks. This fallback is not full index coverage. The scanner downloads roughly two years of adjusted daily prices and requires at least 210 usable bars per stock.

- **Uptrend:** close above the 200-day SMA and 50-day SMA above the 200-day SMA.
- **Downtrend:** close below the 200-day SMA and 50-day SMA below the 200-day SMA.
- **Mixed:** neither of those combinations.
- **Relative volume:** latest volume divided by the preceding 50-day average, not the intraday time-adjusted relative volume in In play.
- **Distance from high:** close divided by the maximum high in the latest 252 bars, minus one.
- **Indicative stop/target:** price minus 1.5 ATR / price plus 3 ATR. These are reference levels, not guaranteed fills or automatic orders.

### Exact Setup Conditions

| Setup | Current rule |
| --- | --- |
| Breakout | Close at least 99.5% of the previous rolling 251-bar high (at least 200 bars), relative volume at least 1.5, and close above previous close. This can trigger just below the prior high. |
| Pullback | Uptrend, close within -2% to +1.5% of the 21-day EMA, and RSI between 40 and 60 inclusive. |
| Squeeze | Bollinger width at or below its rolling 126-bar tenth percentile (at least 100 observations), with close above the 50-day SMA. The label's "tightest" language represents a lower-decile test, not literally a single absolute minimum. |
| Oversold | RSI below 35 while close is above the 200-day SMA. This is different from the usual RSI-30 warning elsewhere. |
| Golden cross | The 50-day SMA crosses from at/below to above the 200-day SMA; the flag remains active if this occurred in the last ten bars. |

### Setup Historical Outcomes

The scanner looks at new signals in the last 252 bars. A signal is counted only when that same setup has not fired in the prior ten bars. It measures forward close-to-close returns after 5, 10 and 20 trading bars. Win rate means positive forward return, not that the displayed stop/target strategy was profitable. The 20-bar statistics also include median return, frequency of at least +5%, and mean excess return versus SPY where available.

By default this is a **current-constituent exploratory sample**, subject to survivorship bias. A documented point-in-time membership dataset can be selected with `RESEARCH_UNIVERSE_SOURCE`. Membership must have been known by the signal-date US market close. Missing historical membership or required prices suppress that historical summary. Neither mode turns descriptive forward returns into portfolio P&L or proves an edge.

The default "all setups" filter requires at least one active setup; "any" includes all analyzed stocks, including those with no signal. Additional controls filter sector and minimum RS (initially zero). Default order is descending RS, with column sorting available. Sector leadership is an aggregation of the scan, not another independent quality screen.

The scan refreshes in the background when older than 36 hours; cached results can remain visible while it builds. Read the displayed update time and coverage status.

Source: [backend/scanner.py](backend/scanner.py), [frontend/src/components/Ideas.jsx](frontend/src/components/Ideas.jsx).

## Wheel: Candidate Qualification

The Wheel scanner searches the stored setup-scan universe. It does not evaluate every listed stock or every listed option. The scanned stock universe and its data coverage therefore constrain the result before any Wheel-specific rule runs.

### Stock Quality Pool

All of the following are required:

| Rule | Current threshold | Intended purpose |
| --- | --- | --- |
| Trend | `uptrend` from the setup scanner | Avoid selling puts into the scanner's downtrend classification. |
| Daily ATR / price | At most 3.5% | Prefer lower daily price variability. |
| Distance below the recent high | No more than 20% below | Avoid deeply damaged price structures. |
| Relative-strength rating | At least 40 | Exclude weaker relative performers. |
| Stock price | $10 through $1,000 inclusive | Bound the candidate price range. |

Qualifying stocks are sorted by `RS rating / max(ATR%, 0.5)`. Only the first 60 proceed to options analysis. This favors relative strength per unit of daily range, not the highest possible option yield. Missing inputs generally fail the pool. Implementation detail: this pool uses truthiness-based defaults for some numeric fields; an exact zero distance from the high is currently treated like a missing distance and excluded.

These are technical quality proxies. The scanner is not certifying balance-sheet quality, a fair valuation, or that the user would actually want to own the shares after assignment.

### Expiration Selection

| Mode | Inclusive expiry window | Target |
| --- | --- | --- |
| Default | 21-50 days to expiry | 35 days |
| Short-dated checkbox | 7-20 days to expiry | 14 days |

Expired contracts are excluded. Within the selected window, the scanner prefers expirations strictly before the known earnings date. If none are available, it can still examine an expiry through earnings and flag that candidate. Unknown earnings do not stop expiry selection itself.

Among the surviving dates, standard monthly expirations are preferred over weeklies; the date nearest the target DTE is then selected. Consequently, the closest date overall does not always win. The scanner does not fall back outside the selected window. Default and short-dated scans have separate caches. Short-dated candidates carry a near-expiry gamma-risk warning.

### Contract Qualification

- Analyze out-of-the-money puts for the selected expiry using the shared option-chain helpers.
- Target approximately 0.15 absolute delta. Reject the selected contract if its delta exceeds 0.22.
- Reject contracts classified as `thin` by the shared liquidity rule.
- Require midpoint-based simple annualized premium of at least 7%.
- Use one standard contract as 100 shares; cash collateral is `strike * 100`.

For stock price `S`, strike `K`, premium per share `M`, and calendar days `D`:

| Display | Calculation |
| --- | --- |
| Premium per contract | `M * 100` |
| Return on strike collateral | `M / K * 100%` |
| Annualized premium | `M / K * 365 / D * 100%` |
| Downside cushion | `(S - K) / S * 100%` |
| Expiry breakeven | `K - M` |
| Approximate expected move | `S * ATM IV * sqrt(time in years)` |

Annualization assumes repeatability that is not established. It is not expected annual profit, and it omits the economic consequences of stock losses and assignment. Modeled probability of finishing in the money is presented as an assignment proxy; actual early assignment is not modeled by that number.

### Ranking Score

The backend ranks candidates with this weighted heuristic:

| Component | Points |
| --- | --- |
| Annualized premium | `min(annualized %, 40) / 40 * 45` |
| Relative strength | `RS rating / 99 * 20` |
| Put strike below the lower expected-move boundary | +15 |
| Liquidity | Good +10; OK +5 |
| ATM IV greater than 1.1 times estimated realized volatility | +5 |
| Modeled probability of expiring out of the money | `(1 - p_ITM) * 5` |
| Known earnings on or before expiry | -30 |

The volatility comparison uses the scanner's approximation `ATR% / 1.25 * sqrt(252) / 100`, not an independently fitted realized-volatility model. The score is not a calibrated probability, expected return, or validated measure of safety. A candidate inside the expected move is flagged rather than automatically excluded by this stage.

### Account-Aware Capital Plan

The planner is stricter than the discovery scan. It requires sign-in and uses recorded account positions.

1. Treat entered capital as **total account cash including existing reserves**. Subtract recorded option cash requirements first.
2. Calculate the allocation base as entered cash plus recorded stock purchase cost. This is not live net liquidation value or broker buying power.
3. Include recorded stock cost and option collateral in existing ticker and sector exposure.
4. Default to a 25% per-name cap and two names per sector, with user controls. Apply a fixed 40% sector exposure cap.
5. Reject a candidate snapshot older than three hours. Block new allocations if existing calls are uncovered or an existing position's sector is unknown.
6. Require a known earnings date and no earnings on or before expiry. Recheck current earnings data; the display checkbox cannot relax this requirement.
7. Refresh the stock price and exact put quote. Require a usable quote, absolute delta at most 0.22, and bid/ask spread divided by midpoint at most 25%.
8. Compare candidate daily returns against other exposed tickers over six months. Require at least 40 overlapping observations; reject missing/non-finite correlations or correlation at least 0.8. Accepted new picks join the exposure set for subsequent comparisons.
9. Recheck that remaining DTE is within the selected default or short-dated window.
10. Estimate per-contract premium using `max(bid * 100 - $1, 0)`, not the scanner midpoint. Require positive premium.
11. Allocate whole contracts within remaining name capacity, sector capacity, and available cash, processing candidates in scan-score order. Skip unknown candidate sectors.

The result can legitimately be an empty plan. It does not buy stocks, sell puts, submit broker orders, or validate actual broker margin. Its monthly and annualized income values are simple projections, not forecasts. Recorded positions must be complete for the reserve and concentration checks to be meaningful.

Scans older than three hours trigger a background refresh when requested; cached results can remain visible during rebuilding. Discovery freshness and planner eligibility are separate checks.

### Wheel Page Controls and Management Entry Points

- **Cash available:** a display filter; one candidate contract must fit the entered cash. A blank value means no display cash cap. It is not the account-aware planner's reserve calculation.
- **Skip trades that hold through earnings:** checked by default. Turning it off can reveal known earnings-overlap candidates, but does not relax the planner's earnings exclusion.
- **Unknown earnings:** the candidate-card list always hides these, even if the skip-earnings checkbox is off. Thin-liquidity cards are also always hidden here. This differs from the single-stock Income view's show-with-warning behavior.
- **Short-dated: 7-20 days:** changes which expiry is scanned; it is not just a filter over the default contracts. Also switches the planner's data/window and clears the previously displayed plan.
- **Candidate count:** display the first 12 remaining ranked candidates.
- **Capital planner defaults:** $50,000 entered account cash, 25% per name, two names per sector. These are editable starting inputs, not a claim about the user's real account.
- **Ask about any ticker:** a separate single-stock Wheel assessment and delta ladder, not an expansion of the S&P scan. Its date-selection behavior is documented with the management rules below.
- **Manage a wheel position:** repair/roll an existing put or assess covered calls after assignment. Candidate shortcuts prefill this tool; they do not record a fill or perform assignment.

The on-screen "take profit at about 50%" and covered-call guidance are management heuristics, not automated instructions or guarantees against a loss. An assignment-adjusted cost estimate does not include every tax, fee, or financing effect.

Source: [backend/wheel.py](backend/wheel.py).

## Shared Options Rules

The main implementation is [backend/options_analytics.py](backend/options_analytics.py). These rules apply where the individual feature calls the shared helpers; they are not a universal guarantee that every tool enforces identical checks.

### Quotes, Models, and Dates

- Option expirations and chains use Yahoo first and CBOE delayed data as fallback. Expirations are normally cached for one hour; chains for five minutes.
- A usable two-sided midpoint requires finite bid/ask, `bid > 0`, and `ask >= bid`. The app does not invent a missing quote from intrinsic value. Protective-wing lookup can use a positive ask when its bid is zero; such a wing attracts a liquidity warning.
- Model IV is solved from the midpoint using Black-Scholes with a fixed 4% risk-free rate, searched between 1% and 500% annual volatility. If solving fails, a provider IV strictly between 3% and 500% may be used. This model does not fully represent American early-exercise or dividend effects.
- Absolute delta and model probability of finishing in the money are different quantities. Neither is a guarantee of assignment or profit.
- DTE is based on the New York calendar date. A contract is considered live until 4 p.m. Eastern on the listed expiry. Model time uses actual seconds until that close, floored at one hour. Product-specific exercise cutoffs and nonstandard settlement conventions are not modeled by this generic rule.
- "Monthly" means a Friday dated between the 15th and 21st. This is a calendar heuristic, not a full exchange-holiday contract classification.

### Liquidity and Strike Selection

Spread percentage is `100 * (ask - bid) / midpoint` for strictly `ask > bid > 0`.

| Classification | Rule |
| --- | --- |
| Good | Open interest at least 500 and spread at most 8%. |
| Thin | Open interest below 100 or spread above 20%. |
| OK | Remaining cases. |

The classification helper treats a missing spread percentage as zero; callers still need their own quote validation. In particular, a locked bid/ask can produce a missing spread percentage even though its midpoint is valid. Do not interpret a liquidity label alone as proof of current tradability.

The income/Wheel strike picker first prefers OI at least 100 and spread at most 25%. It favors strikes within 0.05 delta of target; if none exist, it uses the closest candidate. A deviation over 0.12 rejects the pick. Thus the picker can consider a 20-25% spread that the final liquidity classifier calls thin. Some views then reject it; Income can display it with a warning.

Among similarly placed strikes, the score rewards target-delta proximity and logarithmic OI, and penalizes wide spreads. OI contribution saturates near 10,000 contracts. OI is a liquidity proxy, not a promise that today's order can be filled.

The general liquid-expiry selector considers the six expiries nearest the requested target within the requested window. It scores near-money OI (strikes within 10% of spot), distance from target, and a 0.1 bonus for a monthly. The formula is `log10(OI + 1) / log10(maxOI + 1) - 0.5 * abs(DTE - target) / windowWidth + monthlyBonus`, with protective minimum denominators. This differs from Wheel's simpler monthly-first rule.

### Earnings Data

Finnhub and Yahoo earnings dates are combined. Reported/past dates are removed from upcoming candidates; the earliest remaining date is selected. Source disagreement can produce an estimated/unconfirmed label. Agreement from multiple sources, or near-date agreement within one day, drives the confirmation heuristic. This is provider corroboration, not issuer confirmation. Results are cached for six hours.

Unknown earnings are **not cleared event risk**. They block Directional recommendations, Income contract sizing, and the Wheel capital plan. Other descriptive tools may still show data and warnings.

## Options Hub: Volatility

This view compares options-implied movement with recent realized movement and shows weekly/monthly expected ranges plus earnings-move context.

| Metric or classification | Rule |
| --- | --- |
| Monthly IV expiry | Target 30 DTE, liquid-expiry window 20-60; fallback nearest target within 5-120. |
| Weekly expiry | Target 7 DTE within 4-12. |
| ATM IV | Up to four calls and four puts nearest spot, inverse-distance weighted; quoted spreads above 40% are excluded from the weighted set. Nearest-strike IV is a fallback. |
| Realized volatility | Rolling 20-day standard deviation of daily log returns, annualized with `sqrt(252)`. |
| IV rank | `(current IV - historical minimum) / (historical maximum - minimum) * 100`; flat history gives 50. |
| IV percentile | Fraction of stored observations strictly below current IV, multiplied by 100. |
| History requirement | At least 20 stored daily observations within the last 365 days. This is not necessarily a complete year. Snapshots are recorded during the market-open check. |
| High/low IV with history | High when rank >=60; low when rank <=25; otherwise normal. |
| High/low without rank | Use IV/RV: high >=1.25, low <=0.9, otherwise normal. Missing both leaves classification unavailable. |
| Displayed expected range | Spot plus/minus `spot * IV * sqrt(max(DTE, 1) / 365)`. |

The text "premium expensive/cheap" is relative to these heuristics. It is not an arbitrage test or a recommendation to sell/buy automatically.

### Earnings Moves

The earnings panel compares up to 12 historical report reactions with the currently priced ATM straddle for the next event. Before-open and after-close reports use different close-to-close pairs. The next earnings date must be within 45 days to calculate its implied move; the expiry must cover the reaction day. Implied move is `(ATM call midpoint + ATM put midpoint) / spot`, not the same calculation as a one-standard-deviation IV range.

Implied move divided by average absolute historical reaction is called rich at >=1.2, cheap at <=0.85, otherwise fair. Historical implied estimates exist only when the app actually saved a snapshot on the prior calendar day during market hours; missing snapshots are not reconstructed. Small samples and changing event conditions limit this comparison.

## Options Hub: Income / Sell Premium

### Four Modes

| Mode | Structure | Sizing input | Main displayed risk |
| --- | --- | --- | --- |
| Covered calls | Sell an OTM call against shares | Shares available | Share downside remains; gains above strike are capped. |
| Cash-secured puts | Sell an OTM put with strike cash reserved | Cash available | Obligation to buy 100 shares per contract at strike. |
| Put credit spreads | Sell a put and buy a lower-strike put | Risk budget | Width minus credit, times 100 per spread. |
| Iron condors | Put credit spread plus call credit spread | Risk budget | Wider wing width minus combined credit, times 100. |

Covered calls, cash-secured puts and put spreads use Conservative/Balanced/Aggressive target deltas of 0.10/0.16/0.25. Condors use 0.08/0.12/0.16 on each short side. These names describe construction targets, not suitability or risk certification.

Default expiry targets about 35 DTE. It first seeks a liquid pre-earnings expiry in 20-50 days, then 10-50 days. If that fails, it seeks 20-50 days without the pre-earnings restriction; the surrounding function can fall back to the first selectable live expiry. The manual list includes live expiries up to 75 days away. **The actual selected date and earnings warning govern; the default is not guaranteed to end before earnings.**

Spread wing width starts with the largest value among $0.50, $1, $2.50, $5, $10, $25, $50 not exceeding 2.5% of spot, defaulting to $0.50. Wings near half to twice that width are preferred, with same-side farther-OTM fallback and OI preference. A valid midpoint credit must be positive and below the spread width. The "natural" estimate sells at bid and buys at ask; it is not a guaranteed fill.

### Safety Labels Versus Sizing

Backend checks cover non-thin liquidity, strikes outside the expected move when available, spread credit at least 10% of width, earnings overlap, and expiry within six days. Zero failed checks produces `safer`, one `caution`, and two or more `risky`. Missing expected-move data means that check is not performed; a label is not comprehensive clearance.

The frontend now keeps returned ideas visible even when they cannot be sized:

- Wide single-leg spreads above 20%, OI below 100, unknown OI, and thin/unknown liquidity produce execution cautions rather than hiding the idea.
- Missing/crossed/non-finite quotes block sizing. Spread sizing requires valid credit/width data and a positive natural credit no greater than midpoint credit.
- Unknown earnings or earnings on/before expiry block sizing.
- Missing/insufficient cash, share coverage or risk budget blocks sizing; the card remains visible with its reason.
- Covered-call quantity is whole hundreds of entered shares; CSP quantity is whole contracts fitting strike collateral; spread quantity is whole units fitting maximum loss. These calculator inputs are not independently checked against a broker account or other outstanding orders.

For example, bid $0.32 and ask $0.40 give midpoint $0.36 and a 22.2% spread. That is an execution warning, not a reason to erase the card. At a $50 strike, one CSP needs $5,000 collateral; adequate cash alone does not clear earnings or quote checks.

Premium and probability displays remain estimates. The user guidance about taking 50% profit or rolling is not an automatic trading rule. Defined-risk expiry formulas assume the specified legs are maintained; early assignment and execution risks remain.

Source: [frontend/src/components/IncomeIdeas.jsx](frontend/src/components/IncomeIdeas.jsx).

## Options Hub: Directional

The user supplies bullish/bearish direction, budget, and a risk/time-horizon selection. Bullish comparisons can include shares, long calls and bull-call debit spreads; bearish comparisons use long puts and bear-put debit spreads, not naked short stock.

| Selection | Preferred inclusive DTE window | Target DTE | Bought-option target absolute delta |
| --- | --- | --- | --- |
| Extreme / 0DTE-this week | 0-6 | 0 | 0.45 |
| High / near-dated | 7-21 | 14 | 0.40 |
| Moderate | 28-50 | 38 | 0.50 |
| Low / LEAPS | 180-900 | 365 | 0.75 |

These are preferred windows, unlike the strict Wheel scan windows. LEAPS can fall back to the longest expiry if at least 120 days away; the general final fallback chooses nearest target within 0-1,000 days. Always inspect returned DTE. "Low" is a relative category within this calculator, not low risk in absolute terms.

The long-option builder first seeks the target delta. If unaffordable, it can choose an affordable alternative with delta at least 0.20 and marks it as stretched. Debit spreads buy near target delta and sell near an expected-move-based strike; they can narrow the wing until one spread fits the budget. Whole quantities are `floor(budget / unit cost)`. Midpoints determine the initial cost estimates.

Only ideas finally classified as good/OK liquidity remain eligible. Unknown earnings or earnings on/before the selected expiry suppress **all** recommendations, including the shares comparison. No liquid affordable candidate produces an explicit no-trade reason; there is no thin-market recommendation fallback.

The deterministic "best fit" order is:

1. For bullish direction, prefer shares if budget buys at least 100 shares.
2. High/extreme: prefer a non-stretched long option unless high IV and an available spread favor the spread; otherwise use the spread if available.
3. Moderate: prefer a debit spread if available.
4. Low: prefer non-stretched LEAPS; otherwise shares if available.
5. Final fallback among eligible structures: spread, long option, shares.

This comparison is a heuristic, not portfolio optimization or a validated expected-return ranking. An option's maximum loss can be the entire debit; a stop order cannot guarantee the quoted loss limit during a gap.

## Wheel: Ask, Assigned Calls, and Roll / Repair

### Ask About Any Ticker

Shows the technical quality checks, a put ladder targeting 0.10/0.15/0.20/0.25 delta, model movement, and earnings context. It tries the default Wheel 21-50-day expiry selection, then a 14-60-day fallback. The short-dated scan checkbox does not change this separate tool. The quality checklist does not include the scan pool's $10-$1,000 price bound or top-60 selection, so "passes screen" here is not identical to appearing in the ranked universe scan.

An optional AI verdict is Good/Caution/Avoid with reasons. Its suggested strike must be one of the computed ladder strikes or is discarded. The AI is not allowed to invent a new tradable strike; its narrative is still fallible. Deterministic analysis caches for five minutes, AI commentary for 30 minutes.

### Covered Calls After Assignment

Uses entered cost basis and shares. Only OTM calls with strike at/above cost basis are considered; contracts are `floor(shares / 100)`. Target deltas are 0.15, 0.25 and 0.35, but labels follow actual selected delta: below 0.20 "Keep the shares", through 0.32 "Balanced", above that "Max premium".

When shares trade below cost, the tool can add the lowest strike at/above cost as "Exit at cost". If nothing suitable is found, it examines longer dates through 120 DTE, seeking the first at-cost call paying at least 0.5% of cost, otherwise the highest premium found. Earnings and liquidity remain visible warnings; this descriptive tool does not apply every planner exclusion. Strike-at-cost is a gross-price safeguard, not a guarantee against net loss after fees, taxes, financing or an inaccurate entered basis.

### Roll / Repair

Supports cash-secured puts, covered calls and put credit spreads. It validates the existing expiry/strike quote; a put spread requires a lower long strike. "Tested" in the calculation means in the money or delta at least 0.40; the accompanying generic management text mentions approximately 0.50, so the flag is deliberately earlier than that prose guideline.

- Search up to ten later listed expiries, beyond current DTE but no more than 63 additional days, with new expiry at least seven days away.
- Consider unchanged strikes or improvements away from spot, no more than 20% of spot in strike distance. A put spread preserves wing width.
- Display candidates with positive new midpoint credit and nonnegative midpoint net roll credit.
- Also calculate natural-price net credit: new sale bid minus wing ask, less old closing ask/wing bid and $2 per single-leg roll or $4 per spread roll.
- Mark a "best" roll only for a tested position, with known earnings, no earnings overlap, non-thin liquidity, at most 45 added days, and nonnegative natural credit after those fees.
- Rank preferred rolls by strike improvement, fewer added days, then natural net credit. Displayed alternatives include closing, accepting put assignment, or allowing covered shares to be called away.

A displayed midpoint-credit roll may fail the stricter "best" criteria. Rolling extends exposure and realizes/closes one obligation while opening another; a credit does not establish lower risk or erase prior economic losses. No button submits an order or proves that a fill occurred.

## Ideas: In Play

Choose All market, S&P 500, or Nasdaq 100. All market combines upstream mover screens and most-active results; if the mover screens fail, index-member chart data is a fallback. Index views attempt member quotes and switch to chart data when coverage is below 80%. "All market" is therefore a discovery sample, not exhaustive exchange coverage.

The final pass requires a usable current/previous price and average volume of at least 50,000 shares. Non-equity quotes and symbols containing a period are skipped. Relative volume divides reported volume by average daily volume times the elapsed regular-session fraction; it prefers a ten-day volume average, with a three-month fallback.

- All-market candidates need relative volume >=1.5, or an absolute opening gap >=4%, or an absolute premarket change >=4%.
- Index views do not require that outlier test; they rank qualifying members.
- Rank = `relative volume * max(abs(regular-session change), abs(premarket change), abs(opening gap))`.
- Return up to 40 all-market rows or 60 index rows. Only the top 20 are enriched with short-interest ratios.
- A nearby earnings timestamp within 36 hours can supply an earnings catalyst. Otherwise, the tool seeks recent company news, avoids generic roundups, and prefers symbol/company-specific headlines. A matching headline is context, not proof that it caused the move.

### In Play Display Filters

| Control | Rule |
| --- | --- |
| Any / Small / Mid / Large cap | Small below $2B; mid $2B to below $10B; large at least $10B. Unknown market cap currently behaves as zero in these UI comparisons. |
| With catalyst | A catalyst object was returned; not independent verification of causality. |
| Unusual volume | All market: at least 2x; index views: at least 1.5x. |
| Relative-volume highlight | All market hot at 3x; index hot at 2x. |
| Both / Up / Down | Positive/negative regular-session change. |
| Minimum price | Default $2; slider $1-$50. |

Short percentage here divides reported short shares by **shares outstanding**, not float. Highlighting at 15% and days-to-cover at five are attention cues, not a squeeze forecast. The feed and page refresh on a three-minute cadence.

Source: [backend/intraday.py](backend/intraday.py), [frontend/src/components/InPlay.jsx](frontend/src/components/InPlay.jsx).

### Reddit Attention

This independent section uses ApeWisdom's `all-stocks` feed for selected stock-focused Reddit communities. It retrieves the first page (up to 100 ranked symbols), normalizes valid records, deduplicates tickers, sorts by provider rank, and displays up to 12. It is **not X coverage**, sentiment analysis, bot filtering or verified news.

The change is `(current mentions / provider's 24h-ago snapshot mentions - 1) * 100`. A missing or zero baseline does not produce infinite growth: it remains unavailable/no baseline. This compares provider snapshots, not a multiweek historical average or a proven unusual-attention threshold. Ticker clicks open stock research for separate investigation.

The provider supplies no reliable update timestamp in this integration; the app labels retrieval time. Absence from the sample does not mean zero mentions.

## Options Flow and Unusual Options

**Dashboard > Analysis > Flow & positioning** examines one ticker. **Ideas > Unusual options** applies the unusual-activity filter across a fixed list of 40 liquid names plus account-held/watched names, capped at 80 unique symbols. CBOE delayed chains are primary here, with Yahoo fallback; only expirations within 0-60 DTE are included.

### Unusual-Activity Qualification

All conditions must hold:

1. Contract volume at least 100.
2. Estimated traded premium at least $25,000 (`volume * midpoint-or-last * 100`). This is not a single identified trade.
3. At least two DTE, excluding zero-/one-day churn.
4. Not more than approximately 5% in the money by the signed moneyness calculation.
5. Volume exceeds OI when OI is positive, or volume is at least 500 when OI is zero.

Rows rank by estimated traded premium. The single-stock view keeps up to 12; the market scan takes up to five per ticker and the top 40 overall. "Bought" means the last price is at least ask minus $0.01; "sold" means it is at most bid plus $0.01; otherwise "mid". These are crude quote-relative labels, not verified aggressor side or opening/closing intent. Delayed/asynchronous quotes, spreads and hedges can invalidate a directional interpretation.

### Positioning Metrics

- **Put/call volume and OI:** summed put amounts divided by calls; no call denominator means unavailable. Narrative calls volume put-heavy above 1.0, call-heavy below 0.6, balanced otherwise.
- **Call/put walls:** strikes with highest summed OI strictly within 80%-120% of spot. These are not proven support/resistance.
- **Gamma exposure proxy:** uses contracts with positive OI and IV strictly between 3% and 300%, assumes positive call/negative put dealer gamma, and scales by 100 shares and a 1% underlying move. Actual dealer inventory is unknown.
- **Gamma flip:** searches 61 hypothetical prices between 85%-115% of spot, finds sign changes, chooses the one nearest current spot, and interpolates. No crossing means no reported flip.
- **Max pain:** strike minimizing aggregate intrinsic payout weighted by OI, for the nearest expiry and nearest monthly. It is not a price target or causal forecast.

Single-stock flow caches for ten minutes; the cross-stock scan for 15. "Most call-heavy" and "most put-heavy" compare ratios, not bullish/bearish certainty.

Source: [backend/options_flow.py](backend/options_flow.py).

## Ideas: Insider Buying and Superinvestors

### Insider Buying

The default lookback is 30 calendar days, querying weekday observations. Eligible records must be SEC-sourced, non-derivative, transaction code `P`, with positive shares and price and a one-to-five-letter uppercase symbol. Only purchases worth at least $10,000 enter company grouping.

- **Cluster:** at least two distinct reported buyer names; rank by buyer count then total purchase value, display up to 25.
- **Large single-insider buying:** one distinct buyer with aggregated purchases at least $250,000; rank by value, display up to 15. The grouping can combine several purchases by that buyer.
- **Average price:** total purchase value divided by purchased shares, not a simple average of prices.
- More than half the nominal lookback days missing feed data marks the feed unavailable. Cache: six hours.

Insider activity can lag transactions and can have motives other than predicting a price increase. The name-based buyer grouping is not a full beneficial-owner identity resolution system.

### Superinvestors

The tracked firms are Berkshire Hathaway, Pershing Square, Baupost, Appaloosa, Duquesne, Third Point, Himalaya, Tiger Global, Lone Pine, Coatue, Viking and ARK. The app compares their latest two regular `13F-HR` filings, not every investment manager. A fund is skipped if its latest filing is more than 200 days old. Reported option positions are excluded from this holdings comparison.

| Label | Rule |
| --- | --- |
| New | CUSIP in the current filing but not the previous filing. |
| Added / Reduced | Absolute change in reported shares at least 10%; direction determines label. |
| Sold | Previous CUSIP absent from the current filing. |
| Top holdings | Largest 15 reported holdings by value per fund. |
| Changes | Largest 25 changes by reported value per fund. |
| Consensus | A mapped ticker appears in at least two tracked funds' top-15 lists; keep the top 15 by holder count. |

CUSIPs are mapped through OpenFIGI; missing mappings remain limitations. A first available filing without a previous comparison can make holdings appear new. A 13F is delayed, incomplete portfolio disclosure: shorts, cash, hedges and subsequent trades may not be represented. "Consensus" is not all-manager consensus. Refresh is triggered after 24 hours, with cached results visible while rebuilding.

Source: [backend/smart_money.py](backend/smart_money.py).

## Ideas: Macro Calendar and Prediction Markets

The Economic calendar groups releases by date, showing times in Eastern Time, impact, actual/consensus/previous values when available, and the next Fed decision. The full view requests 14 days and initially includes medium-impact releases; the compact Dashboard view requests seven days and initially shows high impact only. The checkbox controls display filtering, not options eligibility. Scheduled events and reported dates can change.

### Prediction-Market Context

The separate Polymarket section samples up to 20 economy events and 20 finance events ordered by 24-hour volume, merges their markets, and displays up to 12 qualifying unique markets by market volume.

- Require active, not-closed events and markets, valid locally constructed event URLs, and a future parsed market end time.
- Require exactly Yes/No outcomes and corresponding finite prices between zero and one, summing to within 0.02 of one. Outcome labels determine the displayed Yes price; array position alone does not.
- Display `Yes price * 100`, reported 24-hour volume/liquidity and provider update time. Daily price change is multiplied by 100 and labeled **percentage points**, not percent return. If Yes is not the first outcome, that change is omitted because its mapping is not established.
- Warn on liquidity below $10,000, volume below $1,000, unknown fields, update times older than 24 hours or over five minutes in the future. These are explicit heuristics, not validated trading filters.
- Market end time is not necessarily a scheduled economic release or final resolution time. Read the linked resolution rules; differently worded markets need not be comparable.

Reddit and prediction feeds cache results and failures for ten minutes per server process. One can fail without breaking the other page features. An outage is not displayed as zero interest or zero probability. Neither changes sizing, Wheel rules or automated alerts. They are public read-only integrations, not trading connections. X's paid API is not connected.

Commercial redistribution, attribution and regional terms still require operator review before public deployment. `EXTERNAL_CONTEXT_ENABLED=0` disables these external feeds; default is enabled. See [README.md](README.md#external-market-context).

Sources: [frontend/src/components/EconomicCalendar.jsx](frontend/src/components/EconomicCalendar.jsx), [backend/market_context.py](backend/market_context.py).

## Ideas: Strategy Tester

This is a single-ticker research tool, not a strategy deployment engine. Controls select ticker, timeframe, strategy parameters, long/short/both, round-trip costs, and optional stop/target percentages. Compare-all ranks by average net trade return, not robust out-of-sample superiority.

### Strategies and Defaults

| Strategy | Default settings and signal |
| --- | --- |
| EMA cross | EMA 9 crosses EMA 21; optional intraday VWAP filter permits longs above VWAP and shorts below. Opposite cross exits; the VWAP filter adds a VWAP-side exit. |
| Bollinger Awesome (BBAWE) | EMA 3 crosses a 20-bar Bollinger basis; Awesome Oscillator uses 5/34-bar midpoint averages. Long confirmation requires positive and rising AO, short negative and falling AO. Opposite basis cross exits. |
| VWAP cross | Close crosses session VWAP; excludes a new-day boundary cross. Intraday-only. |
| MACD cross | 12/26 EMAs and nine-bar signal; histogram crossing zero drives entries/exits. |
| Supertrend | Ten-bar ATR, multiplier 3; trend-state flips drive trades. |
| RSI mean reversion | RSI 14 crosses back above 30 for a long, back below 70 for a short; exit at the 50 level. |
| Opening range breakout | First close outside the opening 15 minutes; next-bar entry, stop at the opposite range boundary, at most one trade per day. Intraday-only. |

Supported data: one-/three-minute bars use seven days of one-minute data (three-minute is resampled); five-/15-minute use 60 days; hourly uses one year; daily uses five years. In this engine, **hourly is not marked intraday**, so it can hold overnight and does not support the intraday-only strategies. At least 60 bars are required.

### Simulation and Validation

- Signals use completed bar data and enter/exit on next-bar opens. Intraday positions close at session end; open final positions close on the final bar.
- Stops/targets use bar high/low, with gap-aware open-price handling. If both are touched, the stop is checked first. ORB uses its range stop instead of the generic stop/target pair.
- Default round-trip cost is three basis points per trade. The total/net equity series sums trade percentage returns; it is not a compounded, cash-constrained account simulation. Borrow availability/cost, market impact and realistic capacity are not comprehensively modeled.
- **Fixed-parameter validation:** first 70% development, final 30% holdout split into three windows. Earlier bars warm indicators; positions reset at boundaries. Intraday boundaries align with sessions.
- **Walk-forward selection:** first 50% trains, followed by five approximately 10% forward windows. Candidate settings are the supplied settings plus/minus 25% on one chosen lookback parameter. Each expanding training window chooses the highest total net return with at least five trades and positive net return; otherwise that forward window stays untraded.
- Show double-cost results as sensitivity checks. Retuning after viewing holdout/forward outcomes contaminates those tests.
- Long/short counts, win rate, mean net return, profit factor, summed return and drawdown describe this simulator. The price baseline is a separate buy-open/sell-close daily comparison for intraday data or buy-and-hold for other data; it does not establish equal account exposure or identical cost treatment.

Parameter validation requires finite values; most periods are positive integers up to 500, fast below slow, RSI bands between 0 and 100 with lower below upper, and VWAP filter 0/1. Costs/stops/targets must be finite and nonnegative. Results cache for ten minutes by parameters. None of these checks demonstrates future profitability.

Source: [backend/backtester.py](backend/backtester.py).

## Ideas: Options Track Record

This tab is a **paper-idea log**, not the user's trade history. It records generated CSP, put-spread, iron-condor, Wheel-put, long-option and debit-spread observations; covered calls and share purchases are not included in this paper summary. Wheel recording uses up to the first 20 backend-ranked candidates, not only the 12 visible cards. Income recording occurs before frontend budget/display checks, so a logged idea does not imply the user could or should have sized it.

- Entry is a hypothetical quoted midpoint observation. Stored legs, premium/debit, risk and cost assumptions determine the outcome.
- Settlement uses the exact expiry-date underlying close and each leg's intrinsic payoff. Settlement runs only after the expiry close cutoff (4:15 p.m. Eastern for same-day settlement). A missing exact-date close leaves the observation unsettled, rather than substituting another date.
- New ideas freeze a cost model of $1 commission per leg per side plus $0.01/share slippage per leg per side: $4 round trip per standard contract leg. Legacy observations without recorded costs are excluded from costed results.
- Win rate means positive P&L after those modeled costs. Return on risk divides net P&L by the recorded risk plus modeled costs. "Expired worthless" uses the gross expiry payoff condition, not after-cost profit.
- Groups are by strategy and label, except Wheel puts are grouped together. Repeated/correlated ideas are not independent experiments.

There is no simulation of early assignment, intraday management, actual order fills, reinvestment or portfolio capacity. Viewing a positive paper track record does not establish a tradable edge.

Source: [backend/track_record.py](backend/track_record.py).

## Watchlist

The Watchlist workspace has one sortable quote table, not additional top-level subtabs. Add/remove symbols, drag to reorder, choose manual or column sorting, refresh, click a ticker for Dashboard research, or open the row's alert controls.

Columns include price/change, 52-week high/low, P/E, EPS, market cap, RSI, volume, dividend yield and sector. RSI >=70 is labeled overbought and <=30 oversold. These are visual labels, not automatic trade instructions. Data gaps stay visible as missing fields.

Guest watchlists are local to the browser. Signed-in lists synchronize to the account and unlock account alerts and additional data such as RSI. A side watchlist rail also appears on Dashboard. Old Screener components/bookmarks do not imply a second current navigation tab.

Source: [frontend/src/components/Watchlist.jsx](frontend/src/components/Watchlist.jsx).

## Portfolio: Holdings

Portfolio has **Holdings**, **Portfolio Risk**, and **Income & Performance**. Holdings contains **Stocks / Options**, with current holdings and sold/closed history for each.

### Stocks

Record ticker, shares, entry cost/date; edit lots or record a sale. Selling from a chosen lot uses that lot; a ticker-level sale consumes lots FIFO. Closing more shares than recorded is rejected. Sold/Closed shows recorded realized trades, distinct from open mark-to-market P&L. Multiple purchases remain separate lots rather than silently overwriting acquisition history.

Guest stock holdings live only in browser storage; signed-in holdings are account data. This is a record keeper, not a broker connection. Entering a buy/sell does not place an order, and omitting a real position makes downstream analytics incomplete.

### Import Positions

Signed-in users can expand **Import positions** in Portfolio, upload a positions CSV, preview recognized/skipped rows, then confirm import. It is not a separate Income & Performance tab.

- The file control rejects files over 1 MB. Parsing searches the first 30 rows for recognizable Symbol and Quantity columns; it accepts common column aliases for per-share or total cost and acquisition date.
- Each accepted row becomes a new stock/ETF lot. Positive quantity and positive cost are required; total cost can be divided by quantity when per-share cost is absent.
- Cash/money-market summary rows, shorts and option symbols are skipped. Symbols must match the supported stock-symbol format; dots normalize to hyphens. Processing stops at 500 accepted rows.
- Acquisition-date formats include ISO and common US formats. Missing, future or unrecognized dates become unknown to the parser; the current import flow uses the normal new-lot date fallback (displayed as "today"). Correct this before relying on holding-period/benchmark analytics.
- This is an **append**, not automatic broker synchronization, reconciliation or duplicate detection. Reimporting the same positions can duplicate lots. Preview does not write; confirmation does. It does not import cash balances, order history or full tax-lot adjustments.

### Options

Record long/short, call/put, strike, expiry, premium per share and contract count. Standard contracts use 100 shares. For long options, marked P&L is `(current midpoint - entry premium) * 100 * contracts`; for shorts the sign reverses. Missing valid quotes mean unavailable P&L, not zero value.

The view includes closing, assignment and roll/repair entry points for applicable records. Assignment recording changes the corresponding holdings and option records; it is not an automatic assertion that a broker assigned the contract. Covered-call assignment requires sufficient recorded shares. FIFO/specific-lot operations and assignment are transactional to avoid overselling concurrent records.

Common cash-settled index symbols cannot use the physical-share assignment workflow. Adjusted/nonstandard contracts, corporate actions and tax basis adjustments need external reconciliation. Source edits remain possible, but the signed-in account's audit history retains changes.

Source: [frontend/src/components/Portfolio.jsx](frontend/src/components/Portfolio.jsx), [backend/database.py](backend/database.py), [backend/portfolio_models.py](backend/portfolio_models.py).

## Portfolio: Portfolio Risk

### Position Alerts

Open option records are checked individually using the exact contract quote, canonical earnings data and recorded share coverage. Severity order is Act, Warn, Info, then remaining DTE.

| Trigger | Current rule |
| --- | --- |
| Expired | Past expiry, or same-day after the app's expiry-close cutoff; prompt reconciliation of expiry/exercise/assignment. |
| Short-option profit capture | At least 50% of opening premium captured based on current midpoint. |
| Short strike tested | In the money or absolute delta >=0.40. |
| Near-expiry gamma | At most seven DTE unless the profit-capture action is already present; severity increases with delta >=0.25 or ITM. |
| Uncovered short call | Insufficient unallocated shares for 100 shares per contract. Shares cannot cover multiple short calls simultaneously. |
| Call ex-dividend exposure | ITM call, next ex-date on/before expiry, and remaining extrinsic value below estimated dividend amount. A warning, not proof of early assignment. |
| Early put assignment exposure | ITM short put with less than $0.05 extrinsic value. |
| Long-option profit | Gain at least 100% of entry premium. |
| Long-option decay | Loss at least 50% with no more than 21 DTE. |
| Earnings exposure | Known earnings today through expiry inclusive; short positions Warn, long positions Info. |
| Missing information | Missing quote or unknown next earnings produces explicit incomplete-risk warnings. |

Ex-dividend estimates prefer an announced date, otherwise project the last interval from recent payment history. Insufficient history or a gap over twice the recent payment interval can suppress the estimate. Verify issuer announcements and broker exercise handling.

### Earnings Exposure

Combines recorded stock/option tickers, listing earnings within the next 30 days and reports within the past ten days. It flags option expiries spanning the report, displays date confidence, and can estimate stock-dollar movement as `shares * spot * mean absolute historical reaction`. This is a scenario magnitude, not expected P&L or a probability. Unknown dates are listed as unavailable, not cleared.

### Portfolio Doctor

Doctor primarily analyzes **stock holdings** using current market-value weights. It is not the full option-risk or account-cash engine. Its historical risk series uses today's normalized weights applied to aligned past returns, not the actual historical trading path. At least 30 aligned return observations are required; missing tickers can leave partial coverage.

| Flag | Threshold |
| --- | --- |
| Largest stock | More than 25% of stock value. |
| Largest sector | More than 40%. |
| Effective positions | Below five, where effective count = `1 / sum(weight^2)`. |
| Weighted beta | Above 1.3; normalize over positions with available beta. |
| Average pairwise correlation | Above 0.6. |
| Annualized volatility | Above 30%, from daily-return standard deviation times `sqrt(252)`. |
| Tax-loss review candidates | Individual recorded lots down at least 10%. Not tax-loss eligibility clearance. |

Fallback health score starts at 100 and subtracts 15 for stock concentration, 15 for sector concentration, 10 for fewer than five effective names, 10 for beta above 1.3, and 10 for volatility above 30%. Correlation is a flag but not a separate fallback-score deduction. Strengths include at least eight effective positions and at least four sectors.

When AI is available, **health score can instead be generated by the model** from the facts and clamped to 0-100. It is not guaranteed to equal the fallback formula. The UI colors >=75 positive and <50 negative. Neither version is a calibrated loss probability. Doctor's near-term earnings list uses a separate 14-day market calendar; the dedicated earnings-exposure section is the more detailed position view.

### Stress Scenarios, Correlation and Sector Allocation

What-if changes assumptions for held stocks/options and estimates resulting P&L; it is a scenario tool, not a forecast or execution simulation:

- Stock move slider: -30% through +30%, applied to **every stock equally**. The displayed scenario curve spans -20% through +20%.
- IV slider: -60% through +100%, applied as a relative change to each option's IV, not percentage points. Missing IV assumes 30%; scenario IV is floored at 1%.
- Days-passed slider runs to the last recorded option expiry; Include shares toggles stock P&L.
- Black-Scholes uses 4% interest and current quote anchoring; the current model/mark difference fades as time runs down. At expiry, scenario value becomes intrinsic. The unchanged scenario reproduces the current market mark.
- Any required missing option/stock quote blocks the scenario instead of silently dropping that position. Results compare total scenario P&L with current P&L, not only the incremental future gain.

The correlation heatmap uses three-month daily log returns, aligned on matching start/end date pairs, with at least five common observations and nonzero variance required. It is distinct from Doctor's one-year data and the Wheel planner's six-month check. Correlation is not a permanent relationship or proof of diversification. Sector allocation is based on recorded stock exposure. Missing marks prevent complete stock-value charts; no chart can infer unrecorded accounts or positions.

Sources: [backend/options_desk.py](backend/options_desk.py), [backend/portfolio_doctor.py](backend/portfolio_doctor.py), [frontend/src/components/Portfolio.jsx](frontend/src/components/Portfolio.jsx).

## Portfolio: Income & Performance

This workspace includes the portfolio history chart and seven tabs: **Combined P&L**, **Account ledger**, **Premium cash flow**, **vs S&P 500**, **Dividends**, **Tax**, and **Weekly review**.

### Portfolio Performance Chart

With no closed stock trades, the chart is simply **Invested versus Current**, not a historical time series. With closed trades, it plots cumulative recorded realized stock P&L at closure events and appends today's open-stock P&L. It does not reconstruct daily NAV, historical open-position drawdowns, cash flows or option performance. Use the benchmark tab and accounting report for their distinct, explicitly limited purposes; do not read the smooth chart line as observed daily performance.

### Combined P&L

Groups stock and option results by ticker: realized option P&L plus marked open option P&L plus realized/marked stock P&L. An open short's received premium is offset by its remaining obligation; premium collected is not immediately counted as earned profit. Missing marks suppress affected totals.

Capital shown is current stock purchase cost plus conservatively allocated gross option collateral, not historical capital invested or broker margin. Protective put wings must match ticker, type and expiry and have a lower strike. Each protective contract and each 100-share call-cover block can be allocated only once. Unmatched short puts reserve full strike cash; uncovered calls remain unbounded-risk flags. Credits are not automatically deducted from these gross reserves.

This view is **not a reconstructed Wheel-cycle ledger**. It deliberately omits adjusted tax basis, return percentages and annualized cycle performance where cash flows and strategy links are insufficient. Explicit cycle allocations belong in Account ledger.

### Account Ledger

| Area | Purpose and criteria |
| --- | --- |
| Manual entries | Record fee, deposit, withdrawal, dividend, valuation, or cycle allocation. Monetary entries use cent precision; valuation can be zero, while other monetary entries must be positive. |
| Occurred-at | Real timestamp, converted to UTC; future/invalid timestamps are rejected by validation. This differs from when the server recorded the event. |
| Fee reference | Optionally link a fee to a supported owned ledger event. Fees are not invented for historical fills. |
| Cycle allocation | Explicitly link shares/contracts from a source event to a named strategy/Wheel cycle. Ownership and remaining allocatable quantity are checked; the same quantity cannot be allocated repeatedly. |
| Corrections | Reverse supported manual entries by appending a reversal. Do not edit or delete the immutable audit trail. |
| US informational tax lots | Basis, proceeds, allocated recorded fees and gain for recorded closed lots. FIFO ticker sales and specific-lot sales retain provenance where recorded; legacy unknown acquisitions remain flagged. |
| Time-weighted return | Requires opening/ending total-account valuations and accurate NAV immediately before external flows. Missing necessary boundaries keep TWR unavailable. |
| Change history | Before/after events from holdings, options, closed records and transactions; load additional pages of 200 records. Legacy opening snapshots are labeled, not invented historical transactions. |
| Export | JSON report of the current accounting summary, not a broker statement or filing-ready tax return. |

Only recorded fees/dividends/flows are included. Partial closes allocate opening fees proportionally, with cent-rounding remainder retained for the final quantity. Manual requests use idempotency keys so retrying a failed response need not duplicate an entry.

TWR links subperiod returns around external flows; it is not cash-flow-adjusted P&L divided by starting cash. Enter total NAV including cash, stock and long-option assets and short-option liabilities. Wash-sale adjustments, option-specific tax rules, assignment/exercise tax treatment, corporate actions and cross-account reconciliation are not a complete automated tax engine. The report is US informational accounting only.

### Premium Cash Flow

Displays twelve monthly buckets of premium collected, premium paid, net cash flow and realized option P&L. Short opening premiums are collected at opening; buybacks are paid at close. Long purchases are paid at opening and sale proceeds collected at close. If a legacy close lacks its opening date, the close month is used. Goal progress compares this month's **realized** result with the recorded monthly goal, not merely cash received. The three-month average uses the previous three completed months.

### vs S&P 500

Compares **currently held stock lots** against buying SPY for the same dollars on each lot's recorded acquisition date. It samples a roughly weekly value series, supports up to 200 lots and 40 tickers, and reports recorded realized stock P&L separately. "Alpha" here is a dollar difference from that shadow SPY investment, not risk-adjusted alpha.

It is not total-account TWR: sold holdings, option exposure, cash movements and explicit dividend cash flows are not comprehensively reconstructed. Missing price histories can exclude lots. History providers may use adjusted prices, so this is not a separately audited dividend-reinvestment accounting model.

### Dividends

Uses the last 365 days of reported payments times the **current share count**, for up to 40 tickers. Projects ex-dates by shifting past dates 364 days and lists up to twelve upcoming estimates. Annual income / 12 is a monthly average, not a promised monthly payment schedule. Yield uses current price; yield on cost uses recorded stock cost. Dividend changes/cuts and newly declared schedules can differ from this projection.

### Tax

The Tax tab is a warning/review surface, distinct from Account ledger's informational closed-lot report:

- Review stock losses closed in the past 400 days for same-ticker current lots acquired within 30 days before or after the sale.
- For recent losses without a recorded rebuy, show the 31st-day reminder; recently acquired shares can also trigger a warning about selling older losing lots.
- Review option losses in the past 60 days for same-ticker current option/share entries within 30 days **after** close. This is a conservative ticker heuristic, not a legal determination of "substantially identical" securities.
- Show recorded-lot short/long-term status and flag profitable lots within 60 days of the calculated long-term transition. Missing acquisition dates limit this result.

It cannot see all accounts, spouse/IRA trades, disposed replacement lots or every wash-sale chain. Do not treat absence of warnings as tax clearance. Reconcile with broker records and professional tax guidance.

### Weekly Review

Provides the saved/generated portfolio review and optional phone-delivery settings. It is narrative context based on recorded account information, not an automatic rebalancing instruction or a guarantee that delivery occurred.

Sources: [frontend/src/components/PortfolioInsights.jsx](frontend/src/components/PortfolioInsights.jsx), [backend/portfolio_insights.py](backend/portfolio_insights.py), [backend/options_desk.py](backend/options_desk.py), [backend/accounting.py](backend/accounting.py).

## Fundamentals: Long-Term Criteria

The long-term view reads SEC XBRL annual filings, retaining up to ten fiscal-year observations. Eligible flow periods span 330-400 days and supported forms include 10-K/10-K-A, 20-F and 40-F. It needs an identifiable SEC filer with usable US-GAAP facts; ETFs and some non-US companies may have no meaningful result. Later restatements are generally used, while EPS/share counts use first-filed observations with subsequent split adjustments.

### Growth, Profitability and Valuation

- Free cash flow = operating cash flow minus capex; missing capex is currently treated as zero, which can overstate FCF when reporting is incomplete.
- Margins divide the respective profit/cash-flow measure by revenue. ROE uses positive equity. ROIC approximates `operating income * (1 - 21%) / (equity + long-term debt - cash)` when that denominator is positive.
- CAGR requires positive starting/ending values. Reported spans include revenue 3/5/longest available through nine intervals, and five-year FCF, EPS and share count. A "10-year" series can represent ten observations but only nine growth intervals.
- Historical P/E compares year-end monthly price with positive annual EPS, with split adjustment. At least three historical P/E points and a current P/E are required for the min/median/max/percentile display. This is a sparse annual comparison, not daily P/E history.
- Reverse DCF solves for ten-year FCF growth consistent with estimated enterprise value (`market cap + long-term debt - cash`), using a fixed **9% discount rate and 2.5% terminal growth**. It searches growth between -50% and +100%; invalid/nonpositive cash flow or unsupported valuation can make it unavailable.
- Relative to five-year FCF growth (revenue growth fallback), implied growth at least three percentage points lower is described as modest expectations; at least five points higher as requiring acceleration; otherwise near historical growth. This does not certify fair value.

### Piotroski-Style Score: Nine One-Point Checks

1. Positive ROA.
2. Positive operating cash flow.
3. ROA improves year over year.
4. Operating cash flow exceeds net income.
5. Long-term debt / assets does not increase.
6. Current ratio improves.
7. Share count does not grow more than 0.5%.
8. Gross margin improves.
9. Asset turnover improves.

Missing required facts generally fail the respective check rather than removing it from the denominator. This implementation uses simplified annual ratios, so the result should not be treated as a universally comparable accounting score.

### Altman and Other Flags

Altman Z is `1.2 * workingCapital/assets + 1.4 * retainedEarnings/assets + 3.3 * operatingIncome/assets + 0.6 * marketCap/liabilities + revenue/assets`. Above 2.99 is labeled safe, above 1.81 through 2.99 grey, and <=1.81 distress. The app suppresses it for sectors matching Financial/Bank/Insurance. Missing subcomponents can be treated as zero; the label is a model classification, not solvency certification or a sector-universal bankruptcy model.

Other flags: ROIC >=15% positive and <6% negative; FCF margin >=15% positive; five-year share-count CAGR <=-1% buyback-positive or >=2% dilution-negative; Piotroski <=3 weak; Altman distress negative; long-term debt exceeding five years of positive FCF negative.

Dividend safety uses annual dividends paid / positive FCF: below 60% safe, 60% to below 90% watch, >=90% at risk. The displayed growth streak actually counts consecutive completed years whose **largest single payment** did not fall by more than 0.1%; it can include flat payouts, not just raises. Financials cache for twelve hours.

Source: [backend/fundamentals.py](backend/fundamentals.py).

## Journal and Trade Planning

The Journal workspace has **Trade history**, **Manual journal**, and **Options review**. One **Plan a trade** action in the shared Journal header opens a dialog containing the Pre-Trade Checklist and Position Size Calculator. Planning tools are not repeated inline on each tab. Close or Escape dismisses the dialog; the draft remains while switching Journal tabs, but is not saved across leaving the workspace or changing accounts. Guests can use these tools but need sign-in for saved journal/review data.

### Trade History

Combines recorded closed stock and option records, sorted by closing timestamp descending. It reports gross realized P&L, with recorded fees and net P&L shown separately for options. Historical option entries share these same records, including their actual dates and notes. It does not infer manual stock-journal entries or paper-track-record ideas to be actual trades, and it does not merge them into account results.

### Manual Journal

**Options journal: Log closed option** records a previously unrecorded completed single-leg option directly in the account's closed-options history. Enter ticker, call/put, long/short, strike, expiry, whole contracts, actual opening/closing dates, opening/closing premiums **per share**, total fees for both sides, and notes. Past expiries are accepted. Opening must not follow closing; closing cannot be future-dated or after expiry. Standard 100-share contracts only; this is not an assignment/exercise or adjusted-contract workflow.

Gross P&L is `(opening premium - closing premium) * contracts * 100` for shorts, reversed for longs. Net P&L subtracts recorded fees. For example only, one short put opened at $1.20 and bought back at $0.35 yields $85 gross, or $83.70 after $1.30 total fees. Enter actual fills; an $85 outcome alone does not establish contract details, dates or fees.

The record, audit trail and fee entry save atomically, without creating an open position or a second manual stock-journal entry. Retrying an unchanged submission in the form reuses its request key. A new submission is not automatically matched against existing trades, so do not re-enter a position already recorded in Portfolio. The saved record appears in Manual journal, Trade history, Portfolio closed options and Options review. Fee corrections made through the account ledger update net results; gross trade P&L remains unchanged. Combined fees are recorded on the closing date, not separately allocated to opening/closing cash-flow dates. Broker import, multi-leg grouping and explicit assignment/exercise tax treatment are not provided by this form.

The left-hand **Actions** column provides pencil/edit and trash/delete controls for manually recorded options. Edit pre-fills the form; **Save option changes** updates the same record, recalculates P&L and reverses/replaces its recorded fees atomically. Cancel leaves the saved record unchanged. Delete requires confirmation, removes the manual trade from results and reverses its active fees and cycle allocations while retaining immutable audit history. Editing cannot reduce contracts below an existing cycle allocation; reverse that allocation in the account ledger first. Trades closed from live Portfolio lots cannot be edited through this manual-entry workflow.

**Expiry**, **Opened on** and **Closed on** have visible calendar buttons that open the browser's native date picker, with dark/light theme support. Direct date entry remains available when the browser does not support programmatic picker opening.

**Manual stock journal** remains separate: record long/short direction, shares, entry date/price, optional stop/target, setup tag and notes; add exit date/price when closed. Its statistics and coach below apply only to these stock-style manual entries, not the options journal. Available setup tags are Breakout, Pullback, Gap and go, Opening range, Reversal, Earnings, Trend follow, Squeeze, and Long-term buy. Tags are user classifications, not proof that a scanner rule was satisfied.

| Metric | Rule |
| --- | --- |
| Closed status | Exit price is present. An open entry has no realized P&L. |
| P&L | `(exit - entry) * shares`, reversed for shorts. |
| Initial risk | `abs(entry - stop) * shares` when a meaningful stop was logged. |
| R-multiple | P&L divided by that initial risk; unavailable without it. |
| Win rate | Positive-P&L closed entries / all closed entries; zero is not a win. |
| Expectancy | Mean recorded dollar P&L per closed trade, not a forward forecast. |
| Profit factor | Gross positive P&L / absolute gross negative P&L; unavailable with no loss denominator. |
| Equity/drawdown | Cumulative closed-trade dollar P&L ordered by exit date/ID and drop from its running peak. Not broker NAV. |
| Losing streak | Consecutive closed entries with P&L <=0. |
| Breakdowns | Setup tag, direction, entry weekday, and holding period. |
| Holding buckets | Same-day; 1-5 days; 6-20 days ("1-4 weeks"); over 20 days ("1+ month"); unknown. |

Manual statistics do not automatically include broker fees, financing, tax adjustments or unlogged trades. Editing/removing manual entries changes these analytics; they are not the immutable accounting ledger. AI coaching requires at least five closed manual entries and configured AI access; it uses aggregates plus up to 40 closed entries and can still misinterpret a small sample. "Where your edge is" is a descriptive breakdown, not proof of an edge.

### Options Review

Analyzes recorded closed options, including historical entries, separately from manual stock-journal entries. Shows count, positive-net-P&L win rate, net P&L after recorded fees, average win/loss, profit factor and worst recorded outcome. Unrecorded costs are not inferred. Realized option results in Combined P&L and Premium income also include recorded fees; premium cash-flow totals still exclude fees. Breakdowns are long/short call/put, ticker, exit type, and DTE at opening: <=0, 1-7, 8-30, 31-60, over 60, or unknown.

A zero close price is labeled "zero-price close (reason unrecorded)" rather than assumed to be expiry or assignment. Multi-leg records are not automatically reconstructed into fully linked strategy trades. Options AI coaching requires at least five closed option records and AI access. Its conclusions are separate from the manual-journal coach.

### Pre-Trade Checklist

Required self-reported fields: ticker, thesis, horizon, IV check, earnings-before-expiry answer, structure, maximum dollar loss, maximum loss as account percentage, exit plan if right, exit plan if wrong, and thesis invalidation condition.

The UI withholds "Checklist complete" when a field is blank, ticker format is invalid, maximum loss is not positive/finite, account risk is not positive/finite or exceeds 100%, stated account loss exceeds the 2% guideline, high IV is selected with a long call/put, earnings overlap is marked accidental, or IV was not checked. Intentional earnings exposure does not block this checklist, unlike the stricter automated Directional/Wheel eligibility rules. Editing an answer clears the previous result; Reset clears the answers.

This is a form-completion and heuristic check. It validates numeric ranges and symbol format but does **not** verify that a ticker exists, fetch and verify the entered earnings/IV answers, or reconcile the account percentage to actual buying power. "Checklist complete" means the self-reported answers meet those rules, not that a trade qualifies, is suitable, risk-free or authorized. The result explicitly leaves market data and account risk unverified. The form does not submit an order.

### Position Size Calculator

This is a **long-stock allocation calculator**, not a fixed-risk stop-distance sizing engine:

1. Desired dollars = entered portfolio value times allocation percentage (initially 5%).
2. Available cash defaults to entered portfolio value when blank.
3. Actual whole shares = `floor(min(desired dollars, available cash) / fetched stock price)`.
4. Capital deployed = shares times price; remaining cash = available cash minus deployed capital.
5. Optional stop must be nonnegative and below entry; optional target must be above entry. Portfolio and stock price must be positive/finite, allocation above zero through 100%, and cash nonnegative/finite.
6. Stop scenario loss = shares times `(entry - stop)`; target gain = shares times `(target - entry)`; reward/risk = `(target - entry) / (entry - stop)`.

The stop estimates loss **after allocation**; moving it does not resize shares to a fixed risk percentage. A price gap can exceed the stop scenario. No position or order is created by calculating.

Sources: [frontend/src/components/Journal.jsx](frontend/src/components/Journal.jsx), [backend/journal.py](backend/journal.py), [frontend/src/components/PreTradeChecklist.jsx](frontend/src/components/PreTradeChecklist.jsx), [frontend/src/components/PositionCalculator.jsx](frontend/src/components/PositionCalculator.jsx).

## Chart and Panel Controls

### Price Chart

Available lookbacks: 1D, 5D, 1M, 3M, 6M, 1Y, 2Y, 5Y and Max. Bar intervals: 1m, 5m, 15m, 30m, 1H, 1D, 1W and 1M. Provider history limits mean not every requested range/interval can return the same depth.

Controls include candlestick/line/area rendering, standard versus Heikin-Ashi candles, volume, logarithmic price scale, event markers, expansion, and extended-hours data. Heikin-Ashi is synthetic smoothing, not the actual OHLC execution price: close averages the raw OHLC; open averages the preceding synthetic open/close, initialized from the first raw open/close.

| Indicator/control | Definition or behavior |
| --- | --- |
| SMA overlays | 20-, 50-, 200-bar simple moving averages. Daily defaults are SMA 50/200. |
| EMA overlays | 9/21-bar exponential moving averages. Intraday defaults also include VWAP. |
| Bollinger bands | 20-bar mean plus/minus two population standard deviations. |
| VWAP | Intraday volume-weighted typical price, reset by session/date. |
| RSI panel | 14-period exponentially smoothed gain/loss ratio using alpha 1/14. |
| MACD panel | EMA 12 minus EMA 26, EMA 9 signal and their histogram difference. |
| Stochastic panel | 14-bar %K, with three-bar %D; zero price range remains missing. |
| ATR panel | True range smoothed using `ewm(span=14)` in the stock-data path. This differs from the Wilder-style alpha 1/14 used by some other indicators/tools. |
| Intraday levels | Previous-day high/low/close, premarket high/low, 15-minute and 30-minute opening range; default groups are previous day, premarket and 15-minute range. |

Indicator periods refer to bars, not always calendar days. Chart overlays, setup rules and Strategy Tester can use different sampling/horizon definitions; matching names do not imply identical trades. Level lines describe past/current price structure and are not execution guarantees.

### Other Nested Controls

- **Market Overview:** Top movers switches among Gainers, Losers and Most active. Sector performance switches Today, 1W, 1M, 3M and sorts by the chosen return. It also shows upcoming earnings for tracked stocks.
- **Financial statements:** Income Statement, Balance Sheet, Cash Flow; annual/quarterly selection and key/all-row display. Missing fields and incomparable fiscal periods require care.
- **Ownership:** Institutional holders and Insider transactions. These are the selected stock's provider disclosures, separate from Ideas' cross-company insider cluster filter.
- **Thesis:** Save/edit the user's thesis and review its Intact/Weakening/Broken status. These are AI assessments of the recorded thesis and available evidence, not binding eligibility rules.
- **Tooltips and tour:** Explain terminology/navigation. They do not change calculations or clear risk constraints.

Sources: [frontend/src/components/CandleChart.jsx](frontend/src/components/CandleChart.jsx), [backend/stock_data.py](backend/stock_data.py), [frontend/src/components/MarketOverview.jsx](frontend/src/components/MarketOverview.jsx), [frontend/src/components/Financials.jsx](frontend/src/components/Financials.jsx), [frontend/src/components/Ownership.jsx](frontend/src/components/Ownership.jsx).

## Alerts, Notifications and Briefings

### Automatic Stock Alerts

These are distinct from the option-position alerts in Portfolio Risk:

| Alert | Rule |
| --- | --- |
| Daily price move | Absolute daily change >=5% by default; High severity at twice the configured threshold. |
| Volume spike | Reported volume / average volume >=2 by default; High at twice the configured threshold. This is not In Play's session-adjusted relative volume. |
| Near 52-week high | No more than 2% below the reported high. |
| Near 52-week low | No more than 5% above the reported low. |
| Golden/death cross | SMA 50 crosses SMA 200 within the last ten daily bars. |
| Reclaim/lose 200-day | Close crosses SMA 200 within the last three daily bars. |
| MACD cross | MACD crosses its signal within the last two daily bars. |
| RSI event | Crosses the 70/30 boundary within the last three daily bars. This is an event, unlike a static overbought/oversold badge. |

Price and volume defaults can be overridden through server configuration. Notifications are deduplicated by ticker/type/date; crossover notifications use the crossover's date rather than announcing it repeatedly while it remains recent.

### Saved Price/Technical Alerts

Signed-in users can create ticker alerts from Dashboard or Watchlist: price above/below, daily percentage up/down, RSI above/below, or percentage below the 52-week high. Comparisons are inclusive: above means `>=`, below means `<=`; daily-down compares change to the negative of the entered positive threshold.

These check the current condition, not necessarily a newly observed crossing. If the condition already holds at the next scan, it may fire. Custom alerts are **one-shot**: after firing they deactivate, with a notification and optional push. Failed/missing market data can postpone a check; absence of notification does not prove the threshold was never reached.

### Notification Bell and Push

The bell displays saved notifications/unread state, polls approximately every two minutes, and includes push settings. Optional ntfy delivery uses a user-configured topic; a random topic can be generated. Treat the topic as sensitive: someone with access to it may see messages depending on the server's access controls. There is no guarantee of instantaneous delivery, and push delivery is not brokerage order execution.

### Background Schedule

Defaults are server-side and require a running scheduler process:

| Work | Current schedule |
| --- | --- |
| Standard stock alerts | Every 15 minutes during the app's weekday 9:30 a.m.-4 p.m. Eastern window. |
| Custom alerts | About every two minutes during that window. |
| Open-option position checks | Once per market-window day after 10:15 a.m. Eastern. |
| Wheel refresh | Approximately every three hours during the market window after 10 a.m. Eastern. |
| Setup scan refresh | Weekdays after 4:30 p.m. Eastern. |
| Paper-option settlement | Weekdays after 4:45 p.m. Eastern. |
| IV snapshot recording | Market-window days from 3:30 p.m. Eastern. |
| Daily briefing | Weekdays after 8 a.m. Eastern by default. |
| Weekly review | Weekend checks after 9 a.m. Eastern, with saved-period deduplication. |
| Thesis checks | Weekdays after 5 p.m. Eastern for eligible tracked theses. |

The scheduler's market-window helper checks weekday/time, **not a full exchange holiday/early-close calendar**. Restarts, backend suspension, provider limits and failures affect timing. Requests can also generate/cache results on demand; these are not precise execution-time promises.

Daily briefing uses up to 25 alphabetically sorted tracked tickers, shows the five largest absolute percentage movers, upcoming seven-day earnings, and up to two headlines for each of the top three movers. AI can summarize those facts; without AI it emits a rule-based text recap. It is not an exhaustive briefing for accounts exceeding that ticker cap.

Sources: [backend/alerts.py](backend/alerts.py), [backend/scheduler.py](backend/scheduler.py), [backend/config.py](backend/config.py), [frontend/src/components/PriceAlerts.jsx](frontend/src/components/PriceAlerts.jsx), [frontend/src/components/NotificationBell.jsx](frontend/src/components/NotificationBell.jsx).

## News and AI Interpretation

### News Sentiment

Headlines/available summaries receive a score from -1 to +1. With configured AI, scoring requests stock-specific sentiment and relevance; otherwise it falls back to a financial-news lexicon/VADER path. The UI/provider marker distinguishes AI from lexicon scoring.

- Positive: score >0.1; Negative: score <-0.1; Neutral: -0.1 through +0.1 inclusive.
- Aggregate sentiment is the simple mean of included article scores, not weighted by source quality, age or expected stock-price impact.
- AI relevance filtering keeps relevance >=0.3 **only when at least three articles pass**; otherwise the original list remains. Up to twelve articles are returned.
- No articles returns a neutral aggregate with zero counts. That is missing evidence, not an actual neutral consensus.

Headline tone is not a predicted return, verified cause of a price move, or recommendation. Open the original source for context.

### AI Research Brief and Rule-Based Fallback

The consolidated brief covers summary, today's move, bull/bear points, risks, catalysts/levels and a balanced verdict. Input includes quotes, technicals, analyst counts, earnings, macro events and up to eight headlines. Day/Swing/Long-term profiles change the prompt's emphasis. Briefs cache for 15 minutes per ticker/profile and can be shared across users; they are not bespoke account advice.

The fallback counts bullish versus bearish rules to choose stance, with ties Neutral and confidence Low:

| Rule | Stance/condition |
| --- | --- |
| RSI | >=70 bearish; <=30 bullish; otherwise neutral. |
| MACD histogram | >0 bullish; <=0 bearish. |
| Trend | Available uptrend bullish; downtrend bearish. |
| Distance from yearly high | Better than -3% bullish; worse than -25% bearish; middle does not add this signal. |
| Forward/trailing P/E | Both positive: lower forward P/E bullish, otherwise bearish; negative trailing P/E bearish. This is only a rough expectations comparison. |
| Volume | >=1.5 times average adds a neutral unusual-activity flag. |
| ATR | >=4% of price adds a neutral high-volatility flag. |

AI stance/confidence are model outputs, **not the fallback vote count or a calibrated probability**. Model-proposed price levels are retained only within 50%-150% of spot, up to four; that broad sanity range does not verify a technical level. Headline references are checked for valid indices, not for whether they logically prove the explanation.

AI Chat provides follow-up research using its supplied context; it does not receive automatic authority to trade. Thesis checks use the saved thesis, latest available earnings/fundamentals, technicals, analyst counts and news. There is no fixed numeric cutoff for Intact/Weakening/Broken; invalid model statuses default to Weakening. AI outputs across Brief, Chat, Wheel, Doctor and coaching should be checked against their supporting facts and timestamps.

### Remaining Research Labels

- **Relative Strength:** RS >=80 Market leader; >=60 Above average; >=40 Average; otherwise Laggard. The badge's color cutoffs are >=80 and >=50, so its middle color is not the same threshold as the textual Above average label. These are cross-sectional relative-performance labels, not RSI.
- **Analyst Ratings:** provider recommendation distribution, price-target range and upgrade/downgrade history. Recommendation-mean colors use <=1.5, <=2.5, <=3.5 and <=4.5 bands on the provider's buy-to-sell scale. A target is an analyst estimate, not the app's guaranteed destination.
- **Peer Comparison:** selected-stock valuation, scale and beta compared with returned peers. Bars are normalized to the displayed comparison set, not an absolute quality score; being cheap relative to peers does not satisfy Wheel qualification.
- **Dividend History:** selected-stock declared/reported dividend information, annual sums and recent payments. Distinct from Portfolio's current-share income projection and the SEC FCF payout safety classification.
- **Macro impact:** keyword categorization, not a measured future market shock. High includes CPI, payrolls/unemployment, FOMC/Fed-chair items, GDP and PCE. Medium includes PPI, retail sales, ISM, JOLTS, claims, confidence/sentiment, durable goods, ADP, housing, industrial production, trade balance and Beige Book. Unmatched events are omitted. The static FOMC fallback contains 2026 dates and must be maintained for future years.

Sources: [backend/news_sentiment.py](backend/news_sentiment.py), [backend/ai_brief.py](backend/ai_brief.py), [backend/thesis.py](backend/thesis.py), [backend/macro.py](backend/macro.py), [frontend/src/components/RelativeStrength.jsx](frontend/src/components/RelativeStrength.jsx), [frontend/src/components/AnalystRatings.jsx](frontend/src/components/AnalystRatings.jsx).

## Data Sources, Scope and Rule Intent

### Source Map

| Information | Main source/path |
| --- | --- |
| Quotes, OHLC, option chains, dividends, many company fields | Yahoo Finance/yfinance, with provider fallbacks where implemented. |
| News, analyst data, earnings calendars | Finnhub and Yahoo depending on feature/configuration. Options earnings uses the combined canonical helper; not every narrative calendar has identical coverage. |
| Annual fundamentals, insider transactions, fund disclosures | SEC EDGAR/XBRL/Form 4/13F; reporting delays and amendments matter. |
| Scanner membership | Current S&P 500 scrape/cache; point-in-time research requires separately configured membership history. |
| US macro releases | Nasdaq calendar and the maintained Federal Reserve date fallback. |
| Reddit attention | ApeWisdom aggregate observations, read-only. |
| Prediction markets | Polymarket public market data, read-only. |
| Account holdings, fills, journal, fees and cash flows | What the user records/imports, not automatic broker confirmation. |

Quotes can be delayed or stale, and provider symbol coverage can vary. Prices, dividends and option data may use different adjustment/timing conventions. A displayed refresh button can refresh the UI/request while an upstream cache still applies. Read timestamps and incomplete/stale labels; do not substitute unknown values with zero risk.

### Why These Families of Rules Exist

The source establishes what the rules do, but does not establish that each exact threshold was statistically optimized. The following explains their practical role, not a documented proof of optimal parameter choice:

| Rule family | Practical role |
| --- | --- |
| Trend, RS, distance from highs | Favor stronger price histories instead of selecting solely for large option premiums. |
| ATR, delta and expected-move buffers | Bound the style of exposure and distinguish quieter candidates from high-premium/high-risk ones. None is a hard future price boundary. |
| DTE windows | Select an intended time horizon and trade-off between premium rate, gamma exposure and time at risk. Short-dated is a different risk mode, not a shortcut to safer yield. |
| Earnings/calendar checks | Avoid treating a scheduled jump-risk period like an ordinary volatility period. Unknown dates are not evidence of no event. |
| Open interest, spreads and bid-based sizing | Reduce dependence on thin, wide or optimistic midpoint quotes. They do not guarantee executable size. |
| Name/sector/correlation caps and coverage allocation | Keep one idea from consuming the entire allocation or reusing the same collateral/share cover. |
| Quality and valuation flags | Expose accounting/expectation risks that a price chart alone cannot show. |
| Costed out-of-sample research | Separate historical observations from a strategy optimized only on the same sample and make friction visible. Still not proof of future profitability. |
| Explicit accounting and uncertainty | Keep cash received, realized profit, marked liabilities, missing data and paper outcomes from being conflated. |

### Scope and Boundaries

This guide describes the current **React frontend and FastAPI backend**, including profile-hidden views revealed by Show all. It does not treat every component filename as a live navigation item. For example, the older standalone Screener, DCA simulator, PriceChart and separate AI-summary/bull-bear components are not current app workspaces. The legacy OptionsDesk wrapper's tabs are not the current Portfolio navigation; its individual panels are reused in Portfolio/Journal. CSV import is reachable through Portfolio's import section, even though its old tab branch remains in the source.

All monetary examples and standard equity-option multipliers assume the app's USD/100-share conventions unless a view states otherwise. The application is a research and record-keeping tool, not an execution venue, broker-reconciled accounting system or comprehensive tax filing product. A visible idea, favorable score, AI verdict or completed checklist does not override missing-data warnings or independent eligibility/capital checks.

Implementation references throughout the guide are the best starting point when rules change. Updating a threshold in code should also update its corresponding explanation here.