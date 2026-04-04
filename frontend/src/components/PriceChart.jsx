import { useState, useMemo, useCallback } from 'react';
import {
  ResponsiveContainer, ComposedChart, Area, Bar, Line,
  XAxis, YAxis, Tooltip, CartesianGrid, Legend,
  ReferenceLine, ReferenceArea, Brush,
} from 'recharts';

// ── Candle shape helpers ────────────────────────────────────────────────────
function drawCandle(props, fillUp, fillDown, strokeUp, strokeDown) {
  const { x, y, width, height, payload } = props;
  if (!payload) return null;
  const { open, close, high, low } = payload;
  const isUp = close >= open;
  const fill = isUp ? fillUp : fillDown;
  const stroke = isUp ? strokeUp : strokeDown;

  const yScale = (val) => {
    const ratio = (high - val) / (high - low || 1);
    return y + ratio * height;
  };
  const bodyH = Math.max(Math.abs(yScale(open) - yScale(close)), 1);
  const midX = x + width / 2;

  return (
    <g>
      <line x1={midX} y1={yScale(high)} x2={midX} y2={yScale(low)} stroke={stroke} strokeWidth={1} />
      <rect x={x + 1} y={yScale(Math.max(open, close))} width={Math.max(width - 2, 2)}
        height={bodyH} fill={fill} stroke={stroke} />
    </g>
  );
}

function CandlestickStandard(props) {
  return drawCandle(props, '#34d399', '#f87171', '#34d399', '#f87171');
}

function CandlestickHollow(props) {
  const { payload } = props;
  if (!payload) return null;
  const isUp = payload.close >= payload.open;
  // Hollow: up = no fill (transparent), down = filled
  return drawCandle(props,
    isUp ? 'transparent' : '#f87171',
    '#f87171',
    isUp ? '#34d399' : '#f87171',
    '#f87171'
  );
}

function CandlestickHeikinAshi(props) {
  const { payload } = props;
  if (!payload) return null;
  const { ha_open, ha_close, ha_high, ha_low } = payload;
  if (ha_open == null) return null;
  const fakePayload = { open: ha_open, close: ha_close, high: ha_high, low: ha_low };
  return drawCandle({ ...props, payload: fakePayload }, '#34d399', '#f87171', '#34d399', '#f87171');
}

// ── Heikin Ashi calculation ─────────────────────────────────────────────────
function computeHeikinAshi(data) {
  if (!data || data.length === 0) return data;
  const result = [];
  let prevHaOpen = data[0].open;
  let prevHaClose = (data[0].open + data[0].high + data[0].low + data[0].close) / 4;

  for (let i = 0; i < data.length; i++) {
    const d = data[i];
    const haClose = (d.open + d.high + d.low + d.close) / 4;
    const haOpen = i === 0 ? d.open : (prevHaOpen + prevHaClose) / 2;
    const haHigh = Math.max(d.high, haOpen, haClose);
    const haLow = Math.min(d.low, haOpen, haClose);

    result.push({
      ...d,
      ha_open: Math.round(haOpen * 100) / 100,
      ha_close: Math.round(haClose * 100) / 100,
      ha_high: Math.round(haHigh * 100) / 100,
      ha_low: Math.round(haLow * 100) / 100,
    });
    prevHaOpen = haOpen;
    prevHaClose = haClose;
  }
  return result;
}

// ── Indicator definitions ───────────────────────────────────────────────────
const OVERLAYS = [
  { key: 'sma_10',  label: 'SMA 10',  color: '#e17055', dash: '4 2' },
  { key: 'sma_20',  label: 'SMA 20',  color: '#00cec9', dash: '4 2' },
  { key: 'sma_50',  label: 'SMA 50',  color: '#fdcb6e', dash: '6 3' },
  { key: 'sma_100', label: 'SMA 100', color: '#a29bfe', dash: '6 3' },
  { key: 'sma_200', label: 'SMA 200', color: '#ff7675', dash: '8 4' },
  { key: 'ema_9',   label: 'EMA 9',   color: '#55efc4', dash: '' },
  { key: 'ema_21',  label: 'EMA 21',  color: '#74b9ff', dash: '' },
  { key: 'ema_50',  label: 'EMA 50',  color: '#fd79a8', dash: '' },
  { key: 'vwap',    label: 'VWAP',    color: '#ffeaa7', dash: '3 3' },
  { key: 'bb_upper', label: 'BB Upper', color: '#636e72', dash: '5 3' },
  { key: 'bb_lower', label: 'BB Lower', color: '#636e72', dash: '5 3' },
];

const CANDLE_TYPES = [
  { key: 'standard', label: 'Standard' },
  { key: 'hollow',   label: 'Hollow' },
  { key: 'heikin',   label: 'Heikin Ashi' },
];

const tooltipStyle = { background: '#151d2e', border: '1px solid #263350', fontSize: '0.8rem', color: '#e4e8ef' };

// ── Custom crosshair tooltip ────────────────────────────────────────────────
function ChartTooltip({ active, payload, label, candleType }) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const isHA = candleType === 'heikin';
  const o = isHA ? d.ha_open : d.open;
  const c = isHA ? d.ha_close : d.close;
  const h = isHA ? d.ha_high : d.high;
  const l = isHA ? d.ha_low : d.low;
  const isUp = c >= o;

  return (
    <div style={{ ...tooltipStyle, padding: '0.5rem 0.75rem', borderRadius: '6px' }}>
      <div style={{ fontWeight: 600, marginBottom: 4, fontSize: '0.75rem', color: '#888' }}>{label}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 12px', fontSize: '0.8rem' }}>
        <span style={{ color: '#9eafc0' }}>O:</span><span>${o?.toFixed(2)}</span>
        <span style={{ color: '#9eafc0' }}>H:</span><span>${h?.toFixed(2)}</span>
        <span style={{ color: '#9eafc0' }}>L:</span><span>${l?.toFixed(2)}</span>
        <span style={{ color: '#9eafc0' }}>C:</span><span style={{ color: isUp ? '#34d399' : '#f87171' }}>${c?.toFixed(2)}</span>
        <span style={{ color: '#9eafc0' }}>Vol:</span><span>{Number(d.volume).toLocaleString()}</span>
      </div>
    </div>
  );
}

// ── Component ───────────────────────────────────────────────────────────────
const PERIODS = [
  { value: '1d', label: '1D' },
  { value: '5d', label: '5D' },
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
  { value: '2y', label: '2Y' },
  { value: '5y', label: '5Y' },
  { value: 'max', label: 'Max' },
];

const INTERVALS = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1H' },
  { value: '1d', label: '1D' },
  { value: '1wk', label: '1W' },
  { value: '1mo', label: '1M' },
];

export default function PriceChart({ data, events, period, interval, prepost, onSettingsChange }) {
  const [chartType, setChartType] = useState('candle');
  const [candleStyle, setCandleStyle] = useState('standard');
  const [activeOverlays, setActiveOverlays] = useState(['sma_20', 'sma_50']);
  const [showRSI, setShowRSI] = useState(false);
  const [showMACD, setShowMACD] = useState(false);
  const [showStoch, setShowStoch] = useState(false);
  const [showATR, setShowATR] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showVolume, setShowVolume] = useState(true);
  const [logScale, setLogScale] = useState(false);
  const [showEarnings, setShowEarnings] = useState(true);
  const [showDividends, setShowDividends] = useState(true);

  const chartData = useMemo(() => {
    if (!data || data.length === 0) return [];
    return candleStyle === 'heikin' ? computeHeikinAshi(data) : data;
  }, [data, candleStyle]);

  const toggleOverlay = useCallback((key) => {
    setActiveOverlays((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }, []);

  if (!data || data.length === 0) return null;

  const CandleShape = candleStyle === 'heikin' ? CandlestickHeikinAshi
    : candleStyle === 'hollow' ? CandlestickHollow
    : CandlestickStandard;

  const chartHeight = expanded ? 600 : 380;
  const priceDataKey = candleStyle === 'heikin' ? 'ha_high' : 'high';

  return (
    <div className={`card ${expanded ? 'chart-expanded' : ''}`}>
      {/* ── Row 1: Title + Period pills + Expand ─────────────── */}
      <div className="chart-header-row">
        <h3 style={{ margin: 0 }}>Price Chart</h3>
        <div className="chart-period-pills chart-toggle">
          {PERIODS.map((p) => (
            <button key={p.value} className={period === p.value ? 'active' : ''}
              onClick={() => onSettingsChange({ period: p.value })}>
              {p.label}
            </button>
          ))}
        </div>
        <button className="btn-icon chart-expand-btn" onClick={() => setExpanded(!expanded)}
          title={expanded ? 'Minimize chart' : 'Expand chart'}>
          {expanded ? '⊖' : '⊕'}
        </button>
      </div>

      {/* ── Row 2: Interval, Pre/Post, Chart-type, Candle style, toggles ─ */}
      <div className="chart-settings-row">
        <select className="candle-select" value={interval}
          onChange={(e) => onSettingsChange({ interval: e.target.value })}>
          {INTERVALS.map((i) => (
            <option key={i.value} value={i.value}>{i.label}</option>
          ))}
        </select>

        <label className="prepost-toggle" title="Include pre-market and after-hours data">
          <input type="checkbox" checked={prepost}
            onChange={(e) => onSettingsChange({ prepost: e.target.checked })} />
          Pre/Post
        </label>

        <span className="chart-divider" />

        <div className="chart-toggle">
          <button className={chartType === 'candle' ? 'active' : ''} onClick={() => setChartType('candle')}>
            Candle
          </button>
          <button className={chartType === 'line' ? 'active' : ''} onClick={() => setChartType('line')}>
            Line
          </button>
        </div>

        {chartType === 'candle' && (
          <select className="candle-select" value={candleStyle}
            onChange={(e) => setCandleStyle(e.target.value)}>
            {CANDLE_TYPES.map((ct) => (
              <option key={ct.key} value={ct.key}>{ct.label}</option>
            ))}
          </select>
        )}

        <span className="chart-divider" />

        <div className="chart-toggle">
          <button className={showVolume ? 'active' : ''} onClick={() => setShowVolume(!showVolume)}
            title="Toggle volume">Vol</button>
          <button className={logScale ? 'active' : ''} onClick={() => setLogScale(!logScale)}
            title="Log scale">Log</button>
          {events && (
            <button className={showEarnings ? 'active' : ''} onClick={() => setShowEarnings(!showEarnings)}
              title="Toggle earnings overlay">ER</button>
          )}
          {events && events.dividends && events.dividends.length > 0 && (
            <button className={showDividends ? 'active' : ''} onClick={() => setShowDividends(!showDividends)}
              title="Toggle dividends overlay">Div</button>
          )}
        </div>
      </div>

      {/* ── Indicator chips ──────────────────────────────────── */}
      <div className="indicator-toggles">
        {OVERLAYS.map((o) => (
          <label key={o.key} className={`indicator-chip ${activeOverlays.includes(o.key) ? 'on' : ''}`}
            style={activeOverlays.includes(o.key) ? { borderColor: o.color, color: o.color } : {}}>
            <input type="checkbox" checked={activeOverlays.includes(o.key)} onChange={() => toggleOverlay(o.key)} />
            {o.label}
          </label>
        ))}
        <label className={`indicator-chip ${showRSI ? 'on' : ''}`}
          style={showRSI ? { borderColor: '#e056a0', color: '#e056a0' } : {}}>
          <input type="checkbox" checked={showRSI} onChange={() => setShowRSI(!showRSI)} />
          RSI
        </label>
        <label className={`indicator-chip ${showMACD ? 'on' : ''}`}
          style={showMACD ? { borderColor: '#0984e3', color: '#0984e3' } : {}}>
          <input type="checkbox" checked={showMACD} onChange={() => setShowMACD(!showMACD)} />
          MACD
        </label>
        <label className={`indicator-chip ${showStoch ? 'on' : ''}`}
          style={showStoch ? { borderColor: '#00cec9', color: '#00cec9' } : {}}>
          <input type="checkbox" checked={showStoch} onChange={() => setShowStoch(!showStoch)} />
          Stoch
        </label>
        <label className={`indicator-chip ${showATR ? 'on' : ''}`}
          style={showATR ? { borderColor: '#fdcb6e', color: '#fdcb6e' } : {}}>
          <input type="checkbox" checked={showATR} onChange={() => setShowATR(!showATR)} />
          ATR
        </label>
      </div>

      {/* ── Main price chart ─────────────────────────────────── */}
      <ResponsiveContainer width="100%" height={chartHeight}>
        <ComposedChart data={chartData} margin={{ top: 24, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3f" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#9eafc0' }} tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" stroke="#263350" />
          <YAxis domain={['auto', 'auto']} scale={logScale ? 'log' : 'auto'}
            tick={{ fontSize: 11, fill: '#9eafc0' }} tickFormatter={(v) => `$${v}`}
            allowDataOverflow={logScale} stroke="#263350" />
          <Tooltip content={<ChartTooltip candleType={candleStyle} />} />
          <Legend />

          {/* Current price line */}
          {chartData.length > 0 && (
            <ReferenceLine y={chartData[chartData.length - 1].close}
              stroke="#7c6cf0" strokeDasharray="6 3" strokeWidth={1}
              label={{ value: `$${chartData[chartData.length - 1].close.toFixed(2)}`,
                fill: '#7c6cf0', fontSize: 11, position: 'right' }} />
          )}

          {/* Event overlays */}
          {showEarnings && events && events.earnings_date && (() => {
            const dates = chartData.map(d => d.date);
            const ed = events.earnings_date.slice(0, 10);
            return dates.includes(ed) ? (
              <ReferenceLine x={ed} stroke="#fdcb6e" strokeDasharray="4 2" strokeWidth={2}
                label={{ value: '📊 ER', position: 'top', fill: '#fdcb6e', fontSize: 10, offset: 4 }} />
            ) : null;
          })()}
          {showDividends && events && events.dividends && (() => {
            const dates = new Set(chartData.map(d => d.date));
            return events.dividends.map((div) => {
              const d = div.date?.slice(0, 10);
              if (!d || !dates.has(d)) return null;
              return (
                <ReferenceLine key={`div-${d}`} x={d} stroke="#34d399" strokeDasharray="4 2" strokeWidth={1.5}
                  label={{ value: `💰 $${div.amount}`, position: 'top', fill: '#34d399', fontSize: 9, offset: 4 }} />
              );
            });
          })()}
          {showEarnings && events && events.past_earnings && (() => {
            const dates = new Set(chartData.map(d => d.date));
            return events.past_earnings.map((er) => {
              const d = er.date?.slice(0, 10);
              if (!d || !dates.has(d)) return null;
              const beat = er.surprise != null && er.surprise > 0;
              const miss = er.surprise != null && er.surprise < 0;
              const color = beat ? '#34d399' : miss ? '#f87171' : '#fdcb6e';
              const icon = beat ? '✅' : miss ? '❌' : '📊';
              return (
                <ReferenceLine key={`er-${d}`} x={d} stroke={color} strokeDasharray="4 2" strokeWidth={1.5}
                  label={{ value: `${icon} ER`, position: 'top', fill: color, fontSize: 9, offset: 4 }} />
              );
            });
          })()}

          {chartType === 'line' ? (
            <Area type="monotone" dataKey="close" name="Close" stroke="#7c6cf0" fill="#7c6cf020" strokeWidth={2} dot={false} />
          ) : (
            <Bar dataKey={priceDataKey} name={candleStyle === 'heikin' ? 'HA OHLC' : 'OHLC'}
              fill="transparent" shape={<CandleShape />} isAnimationActive={false} />
          )}

          {OVERLAYS.filter((o) => activeOverlays.includes(o.key)).map((o) => (
            <Line key={o.key} type="monotone" dataKey={o.key} name={o.label} stroke={o.color}
              strokeWidth={1.5} strokeDasharray={o.dash} dot={false} connectNulls />
          ))}

          {/* Brush for zoom/pan */}
          <Brush dataKey="date" height={20} stroke="var(--accent)" fill="var(--bg)"
            tickFormatter={(d) => d?.slice(5) || ''} />
        </ComposedChart>
      </ResponsiveContainer>

      {/* ── Volume ───────────────────────────────────────────── */}
      {showVolume && (
        <ResponsiveContainer width="100%" height={80}>
          <ComposedChart data={chartData} margin={{ top: 0, right: 10, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3f" />
            <XAxis dataKey="date" tick={false} />
            <YAxis tick={{ fontSize: 10, fill: '#9eafc0' }} tickFormatter={(v) => `${(v / 1e6).toFixed(0)}M`} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => [Number(v).toLocaleString(), 'Volume']} />
            <Bar dataKey="volume" name="Volume"
              shape={(props) => {
                const { x, y, width, height, payload } = props;
                const isUp = payload.close >= payload.open;
                return <rect x={x} y={y} width={width} height={height} fill={isUp ? '#34d39966' : '#f8717166'} />;
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* ── RSI panel ────────────────────────────────────────── */}
      {showRSI && (
        <>
          <h4 className="sub-chart-title">RSI (14)</h4>
          <ResponsiveContainer width="100%" height={140}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3f" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9eafc0' }} tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" />
              <YAxis domain={[0, 100]} ticks={[0, 30, 50, 70, 100]} tick={{ fontSize: 10, fill: '#9eafc0' }} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [v != null ? Number(v).toFixed(1) : '-', 'RSI']} />
              <ReferenceArea y1={70} y2={100} fill="#f8717115" />
              <ReferenceArea y1={0} y2={30} fill="#34d39915" />
              <ReferenceLine y={70} stroke="#f87171" strokeDasharray="3 3" strokeWidth={1} />
              <ReferenceLine y={30} stroke="#34d399" strokeDasharray="3 3" strokeWidth={1} />
              <ReferenceLine y={50} stroke="#636e72" strokeDasharray="2 4" strokeWidth={1} />
              <Line type="monotone" dataKey="rsi" name="RSI" stroke="#e056a0" strokeWidth={1.5} dot={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}

      {/* ── MACD panel ───────────────────────────────────────── */}
      {showMACD && (
        <>
          <h4 className="sub-chart-title">MACD</h4>
          <ResponsiveContainer width="100%" height={140}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3f" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9eafc0' }} tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10, fill: '#9eafc0' }} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v, name) => [v != null ? Number(v).toFixed(2) : '-', name]} />
              <Legend />
              <ReferenceLine y={0} stroke="#636e72" strokeWidth={1} />
              <Bar dataKey="macd_hist" name="Histogram"
                shape={(props) => {
                  const { x, y, width, height, payload } = props;
                  const val = payload?.macd_hist;
                  return <rect x={x} y={y} width={width} height={height} fill={val >= 0 ? '#34d399' : '#f87171'} />;
                }}
              />
              <Line type="monotone" dataKey="macd" name="MACD" stroke="#0984e3" strokeWidth={1.5} dot={false} connectNulls />
              <Line type="monotone" dataKey="macd_signal" name="Signal" stroke="#e17055" strokeWidth={1.5} dot={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}

      {/* ── Stochastic Oscillator panel ──────────────────────── */}
      {showStoch && (
        <>
          <h4 className="sub-chart-title">Stochastic (%K 14, %D 3)</h4>
          <ResponsiveContainer width="100%" height={140}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3f" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9eafc0' }} tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" />
              <YAxis domain={[0, 100]} ticks={[0, 20, 50, 80, 100]} tick={{ fontSize: 10, fill: '#9eafc0' }} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v, name) => [v != null ? Number(v).toFixed(1) : '-', name]} />
              <ReferenceArea y1={80} y2={100} fill="#f8717115" />
              <ReferenceArea y1={0} y2={20} fill="#34d39915" />
              <ReferenceLine y={80} stroke="#f87171" strokeDasharray="3 3" strokeWidth={1} />
              <ReferenceLine y={20} stroke="#34d399" strokeDasharray="3 3" strokeWidth={1} />
              <Line type="monotone" dataKey="stoch_k" name="%K" stroke="#00cec9" strokeWidth={1.5} dot={false} connectNulls />
              <Line type="monotone" dataKey="stoch_d" name="%D" stroke="#e17055" strokeWidth={1.5} strokeDasharray="3 3" dot={false} connectNulls />
              <Legend />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}

      {/* ── ATR panel ────────────────────────────────────────── */}
      {showATR && (
        <>
          <h4 className="sub-chart-title">ATR (14)</h4>
          <ResponsiveContainer width="100%" height={120}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2a3f" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9eafc0' }} tickFormatter={(d) => d.slice(5)} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10, fill: '#9eafc0' }} tickFormatter={(v) => `$${Number(v).toFixed(1)}`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [v != null ? `$${Number(v).toFixed(2)}` : '-', 'ATR']} />
              <Area type="monotone" dataKey="atr" name="ATR" stroke="#fdcb6e" fill="#fdcb6e20" strokeWidth={1.5} dot={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
}
