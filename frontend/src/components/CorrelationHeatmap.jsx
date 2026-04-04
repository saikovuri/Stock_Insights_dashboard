import { useState } from 'react';
import { fetchReturns } from '../api/stockApi';

function pearsonCorrelation(a, b) {
  const n = Math.min(a.length, b.length);
  if (n < 5) return null;
  const ax = a.slice(0, n);
  const bx = b.slice(0, n);
  const meanA = ax.reduce((s, v) => s + v, 0) / n;
  const meanB = bx.reduce((s, v) => s + v, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) {
    const dA = ax[i] - meanA;
    const dB = bx[i] - meanB;
    num += dA * dB;
    da += dA * dA;
    db += dB * dB;
  }
  const denom = Math.sqrt(da * db);
  return denom === 0 ? 0 : num / denom;
}

function logReturns(prices) {
  const rets = [];
  for (let i = 1; i < prices.length; i++) {
    if (prices[i - 1] > 0 && prices[i] > 0) {
      rets.push(Math.log(prices[i] / prices[i - 1]));
    }
  }
  return rets;
}

function corrColor(r) {
  if (r == null) return '#333';
  // Red for negative, white for 0, green for positive
  if (r >= 0) {
    const g = Math.round(184 * r + 50 * (1 - r));
    const rb = Math.round(50 * (1 - r));
    return `rgb(${rb},${g},${rb})`;
  } else {
    const neg = Math.abs(r);
    const rr = Math.round(209 * neg + 50 * (1 - neg));
    const gb = Math.round(50 * (1 - neg));
    return `rgb(${rr},${gb},${gb})`;
  }
}

export default function CorrelationHeatmap({ tickers }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [matrix, setMatrix] = useState(null);
  const [error, setError] = useState(null);

  if (!tickers || tickers.length < 2) return null;

  const buildMatrix = async () => {
    if (open && matrix) { setOpen(false); return; }
    setOpen(true);
    if (matrix) return;
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.all(tickers.map(t => fetchReturns(t, '3mo')));
      const returnsMap = {};
      tickers.forEach((t, i) => {
        const prices = results[i].map(p => p.close).filter(Boolean);
        returnsMap[t] = logReturns(prices);
      });

      const mat = tickers.map(a =>
        tickers.map(b => {
          if (a === b) return 1;
          return pearsonCorrelation(returnsMap[a], returnsMap[b]);
        })
      );
      setMatrix(mat);
    } catch (e) {
      setError('Failed to load correlation data');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="correlation-wrap">
      <button className="btn-secondary btn-corr" onClick={buildMatrix}>
        {open ? '✕ Hide' : '🔗 Correlation Heatmap'}
      </button>

      {open && (
        <div className="correlation-panel">
          <h4 className="corr-title">Return Correlation (3-month daily returns)</h4>
          {loading && <p className="loading-text">Computing correlations…</p>}
          {error && <p className="error-text">{error}</p>}
          {matrix && (
            <div className="corr-outer">
              <div className="corr-grid" style={{ gridTemplateColumns: `80px repeat(${tickers.length}, 56px)` }}>
                {/* header row */}
                <div className="corr-cell corr-empty" />
                {tickers.map(t => <div key={t} className="corr-cell corr-label-col">{t}</div>)}

                {/* data rows */}
                {tickers.map((rowTicker, ri) => (
                  <>
                    <div key={`lbl-${rowTicker}`} className="corr-cell corr-label-row">{rowTicker}</div>
                    {tickers.map((colTicker, ci) => {
                      const val = matrix[ri][ci];
                      return (
                        <div
                          key={`${rowTicker}-${colTicker}`}
                          className="corr-cell corr-value"
                          style={{ background: corrColor(val) }}
                          title={`${rowTicker} × ${colTicker}: ${val != null ? val.toFixed(2) : 'N/A'}`}
                        >
                          {val != null ? val.toFixed(2) : '—'}
                        </div>
                      );
                    })}
                  </>
                ))}
              </div>
              <div className="corr-legend">
                <span className="corr-neg">-1 (inverse)</span>
                <div className="corr-gradient" />
                <span className="corr-pos">+1 (correlated)</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
