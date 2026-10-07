import { useState, useMemo, useEffect, useRef } from 'react';
import {
  createChart, CandlestickSeries, LineSeries, HistogramSeries, AreaSeries,
  createSeriesMarkers, CrosshairMode, PriceScaleMode, LineStyle,
} from 'lightweight-charts';
import { useTheme } from '../ThemeContext';
import { fetchKeyLevels } from '../api/stockApi';
import Tip from './Tip';

const UP = '#26a69a';
const DOWN = '#ef5350';
const MY_LEVEL_COLORS = { cost: '#7c6cf0', short_call: '#f97316', short_put: '#eab308', long_call: '#22c55e', long_put: '#38bdf8', alert: '#9ca3af' };
const INTRADAY = ['1m', '2m', '5m', '15m', '30m', '1h'];
const DEFAULT_OVERLAYS = { intraday: ['vwap', 'ema_9', 'ema_21'], daily: ['sma_50', 'sma_200'] };

const LEVEL_GROUPS = [
  { key: 'prev', label: 'Prev day H/L/C', keys: ['pdh', 'pdl', 'pdc'], color: '#90a4ae', short: { pdh: 'PDH', pdl: 'PDL', pdc: 'PDC' } },
  { key: 'pre', label: 'Premarket H/L', keys: ['pmh', 'pml'], color: '#ba68c8', short: { pmh: 'PMH', pml: 'PML' } },
  { key: 'or15', label: 'Opening range 15m', keys: ['or15h', 'or15l'], color: '#4dd0e1', short: { or15h: 'OR15 H', or15l: 'OR15 L' } },
  { key: 'or30', label: 'Opening range 30m', keys: ['or30h', 'or30l'], color: '#26a69a', short: { or30h: 'OR30 H', or30l: 'OR30 L' } },
];

const OVERLAYS = [
  { key: 'sma_20', label: 'SMA 20', color: '#29b6f6' },
  { key: 'sma_50', label: 'SMA 50', color: '#ffb300' },
  { key: 'sma_200', label: 'SMA 200', color: '#ab47bc' },
  { key: 'ema_9', label: 'EMA 9', color: '#66bb6a', style: LineStyle.Dashed },
  { key: 'ema_21', label: 'EMA 21', color: '#ec407a', style: LineStyle.Dashed },
  { key: 'bb', label: 'Bollinger', color: '#78909c', keys: ['bb_upper', 'bb_lower'], style: LineStyle.Dotted },
  { key: 'vwap', label: 'VWAP', color: '#fdd835', intradayOnly: true },
];

const PANELS = [
  { key: 'rsi', label: 'RSI' },
  { key: 'macd', label: 'MACD' },
  { key: 'stoch', label: 'Stoch' },
  { key: 'atr', label: 'ATR' },
];

const PERIODS = [
  { value: '1d', label: '1D' }, { value: '5d', label: '5D' }, { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' }, { value: '6mo', label: '6M' }, { value: '1y', label: '1Y' },
  { value: '2y', label: '2Y' }, { value: '5y', label: '5Y' }, { value: 'max', label: 'Max' },
];

const INTERVALS = [
  { value: '1m', label: '1m' }, { value: '5m', label: '5m' }, { value: '15m', label: '15m' },
  { value: '30m', label: '30m' }, { value: '1h', label: '1H' }, { value: '1d', label: '1D' },
  { value: '1wk', label: '1W' }, { value: '1mo', label: '1M' },
];

function heikinAshi(bars) {
  const out = [];
  let prevO, prevC;
  for (const b of bars) {
    const c = (b.open + b.high + b.low + b.close) / 4;
    const o = prevO === undefined ? (b.open + b.close) / 2 : (prevO + prevC) / 2;
    out.push({ ...b, open: o, close: c, high: Math.max(b.high, o, c), low: Math.min(b.low, o, c) });
    prevO = o; prevC = c;
  }
  return out;
}

function fmtVol(v) {
  if (v == null) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

export default function CandleChart({ ticker, data, events, period, interval, prepost, onSettingsChange, myLevels = [] }) {
  const { theme } = useTheme();
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const savedRange = useRef(null);
  const lastData = useRef(null);

  const isIntraday = INTRADAY.includes(interval);
  const [chartType, setChartType] = useState('candle');
  const [candleStyle, setCandleStyle] = useState('standard');
  const [overlays, setOverlays] = useState(isIntraday ? DEFAULT_OVERLAYS.intraday : DEFAULT_OVERLAYS.daily);
  const [panels, setPanels] = useState([]);
  const [showVolume, setShowVolume] = useState(true);
  const [logScale, setLogScale] = useState(false);
  const [showEvents, setShowEvents] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [hoverIdx, setHoverIdx] = useState(null);
  const [levels, setLevels] = useState(null);
  const [levelGroups, setLevelGroups] = useState(['prev', 'pre', 'or15']);
  const [showMine, setShowMine] = useState(true);

  useEffect(() => {
    setOverlays(isIntraday ? DEFAULT_OVERLAYS.intraday : DEFAULT_OVERLAYS.daily);
  }, [isIntraday]);

  useEffect(() => {
    setLevels(null);
    if (!ticker || !isIntraday) return;
    fetchKeyLevels(ticker).then(setLevels).catch(() => setLevels(null));
  }, [ticker, isIntraday, data]);

  // Intraday strings are exchange-local; encoding them as UTC makes the axis show exchange time.
  // Format comes from the data (not `interval`) so a stale fetch during an interval switch can't crash the chart.
  const bars = useMemo(() => {
    if (!data?.length) return [];
    const seen = new Set();
    return data
      .map(d => ({ ...d, time: d.date.length > 10 ? Date.parse(d.date.replace(' ', 'T') + ':00Z') / 1000 : d.date }))
      .filter(d => !seen.has(d.time) && seen.add(d.time));
  }, [data]);

  const candles = useMemo(() => (candleStyle === 'heikin' ? heikinAshi(bars) : bars), [bars, candleStyle]);

  const toggle = (setter) => (key) => setter(prev => (prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]));

  useEffect(() => {
    if (!containerRef.current || !bars.length) return undefined;
    if (lastData.current !== data) {
      savedRange.current = null;
      lastData.current = data;
    }

    const dark = theme !== 'light';
    const text = dark ? '#b4c4d4' : '#374151';
    const grid = dark ? 'rgba(38, 51, 80, 0.45)' : 'rgba(209, 213, 219, 0.6)';
    const border = dark ? '#263350' : '#d1d5db';

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: text,
        fontFamily: 'Inter, -apple-system, sans-serif',
        fontSize: 11,
        attributionLogo: true,
        panes: { separatorColor: border, separatorHoverColor: border, enableResize: true },
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: border, mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal },
      timeScale: { borderColor: border, timeVisible: isIntraday, secondsVisible: false, rightOffset: 4 },
    });
    chartRef.current = chart;

    let main;
    if (chartType === 'line') {
      main = chart.addSeries(AreaSeries, {
        lineColor: '#7c6cf0', topColor: 'rgba(124,108,240,0.35)', bottomColor: 'rgba(124,108,240,0.02)', lineWidth: 2,
      });
      main.setData(bars.map(b => ({ time: b.time, value: b.close })));
    } else {
      const hollow = candleStyle === 'hollow';
      main = chart.addSeries(CandlestickSeries, {
        upColor: hollow ? 'rgba(0,0,0,0)' : UP, downColor: DOWN,
        borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
      });
      main.setData(candles.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    }
    main.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: showVolume ? 0.22 : 0.05 } });

    if (showVolume) {
      const vol = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false,
      });
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      vol.setData(bars.map(b => ({
        time: b.time, value: b.volume, color: b.close >= b.open ? 'rgba(38,166,154,0.45)' : 'rgba(239,83,80,0.45)',
      })));
    }

    const points = key => bars.filter(b => b[key] != null).map(b => ({ time: b.time, value: b[key] }));
    const line = (key, color, pane = 0, extra = {}) => {
      const s = chart.addSeries(LineSeries, {
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra,
      }, pane);
      s.setData(points(key));
      return s;
    };

    OVERLAYS.filter(o => overlays.includes(o.key) && (!o.intradayOnly || isIntraday)).forEach(o => {
      (o.keys || [o.key]).forEach(k => line(k, o.color, 0, { lineStyle: o.style ?? LineStyle.Solid, lineWidth: o.keys ? 1 : 2 }));
    });

    if (isIntraday && levels?.levels) {
      LEVEL_GROUPS.filter(g => levelGroups.includes(g.key)).forEach(g => {
        levels.levels.filter(l => g.keys.includes(l.key)).forEach(l => main.createPriceLine({
          price: l.price, color: g.color, lineWidth: 1, lineStyle: LineStyle.Dashed,
          axisLabelVisible: true, title: g.short[l.key],
        }));
      });
    }

    let pane = 1;
    if (showMine) {
      myLevels.forEach(level => main.createPriceLine({
        price: level.price, color: MY_LEVEL_COLORS[level.kind] || '#9ca3af', lineWidth: level.kind === 'cost' ? 2 : 1,
        lineStyle: level.kind === 'cost' ? LineStyle.Solid : LineStyle.Dashed, axisLabelVisible: true, title: level.label,
      }));
    }
    const guide = (series, price, color) => series.createPriceLine({
      price, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false,
    });
    if (panels.includes('rsi')) {
      const s = line('rsi', '#e056a0', pane, { lineWidth: 2, lastValueVisible: true });
      guide(s, 70, DOWN); guide(s, 30, UP);
      pane++;
    }
    if (panels.includes('macd')) {
      const h = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      h.setData(bars.filter(b => b.macd_hist != null).map(b => ({
        time: b.time, value: b.macd_hist, color: b.macd_hist >= 0 ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
      })));
      line('macd', '#29b6f6', pane, { lineWidth: 2 });
      line('macd_signal', '#ff7043', pane);
      pane++;
    }
    if (panels.includes('stoch')) {
      const s = line('stoch_k', '#26c6da', pane, { lineWidth: 2 });
      line('stoch_d', '#ff7043', pane, { lineStyle: LineStyle.Dashed });
      guide(s, 80, DOWN); guide(s, 20, UP);
      pane++;
    }
    if (panels.includes('atr')) {
      line('atr', '#ffb300', pane, { lineWidth: 2, lastValueVisible: true });
      pane++;
    }
    chart.panes().forEach((p, i) => { if (i > 0) p.setHeight(110); });

    if (showEvents && events && !isIntraday) {
      const times = new Set(bars.map(b => b.time));
      const markers = [];
      (events.past_earnings || []).forEach(er => {
        const t = er.date?.slice(0, 10);
        if (!times.has(t)) return;
        const beat = er.surprise > 0;
        const miss = er.surprise < 0;
        markers.push({
          time: t, position: 'aboveBar', shape: 'circle',
          color: beat ? UP : miss ? DOWN : '#ffb300',
          text: er.surprise != null ? `E ${er.surprise > 0 ? '+' : ''}${er.surprise.toFixed(1)}%` : 'E',
        });
      });
      (events.dividends || []).forEach(dv => {
        const t = dv.date?.slice(0, 10);
        if (times.has(t)) markers.push({ time: t, position: 'belowBar', shape: 'arrowUp', color: '#66bb6a', text: `D $${dv.amount}` });
      });
      markers.sort((a, b) => (a.time < b.time ? -1 : 1));
      if (markers.length) createSeriesMarkers(main, markers);
    }

    const onMove = param => {
      const i = param.logical;
      setHoverIdx(param.point && i != null && i >= 0 && i < bars.length ? Math.round(i) : null);
    };
    chart.subscribeCrosshairMove(onMove);

    if (savedRange.current) chart.timeScale().setVisibleLogicalRange(savedRange.current);
    else chart.timeScale().fitContent();

    return () => {
      savedRange.current = chart.timeScale().getVisibleLogicalRange();
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
    };
  }, [data, bars, candles, chartType, candleStyle, overlays, panels, showVolume, logScale, showEvents, events, theme, isIntraday, levels, levelGroups, myLevels, showMine]);

  if (!bars.length) return null;

  const idx = hoverIdx ?? bars.length - 1;
  const bar = candles[idx];
  const prev = candles[idx - 1];
  const chg = prev ? ((bar.close - prev.close) / prev.close) * 100 : null;
  const height = (expanded ? 620 : 420) + panels.length * 110;
  const hasVwap = bars.some(b => b.vwap != null);

  return (
    <div className={`card ${expanded ? 'chart-expanded' : ''}`}>
      <div className="chart-header-row">
        <h3 style={{ margin: 0 }}>Price Chart</h3>
        <div className="chart-period-pills chart-toggle">
          {PERIODS.map(p => (
            <button key={p.value} className={period === p.value ? 'active' : ''}
              onClick={() => onSettingsChange({ period: p.value })}>{p.label}</button>
          ))}
        </div>
        <button className="btn-icon chart-expand-btn" onClick={() => setExpanded(!expanded)}
          title={expanded ? 'Minimize chart' : 'Expand chart'}>{expanded ? '⊖' : '⊕'}</button>
      </div>

      <div className="chart-settings-row">
        <select className="candle-select" value={interval} onChange={e => onSettingsChange({ interval: e.target.value })}>
          {INTERVALS.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}
        </select>
        <label className="prepost-toggle" title="Include pre-market and after-hours data">
          <input type="checkbox" checked={prepost} onChange={e => onSettingsChange({ prepost: e.target.checked })} />
          Pre/Post
        </label>
        <span className="chart-divider" />
        <div className="chart-toggle">
          <button className={chartType === 'candle' ? 'active' : ''} onClick={() => setChartType('candle')}>Candle</button>
          <button className={chartType === 'line' ? 'active' : ''} onClick={() => setChartType('line')}>Line</button>
        </div>
        {chartType === 'candle' && (
          <select className="candle-select" value={candleStyle} onChange={e => setCandleStyle(e.target.value)}>
            <option value="standard">Standard</option>
            <option value="hollow">Hollow</option>
            <option value="heikin">Heikin Ashi</option>
          </select>
        )}
        <span className="chart-divider" />
        <div className="chart-toggle">
          <button className={showVolume ? 'active' : ''} onClick={() => setShowVolume(!showVolume)}>Vol</button>
          <button className={logScale ? 'active' : ''} onClick={() => setLogScale(!logScale)}>Log</button>
          {!isIntraday && events && (
            <button className={showEvents ? 'active' : ''} onClick={() => setShowEvents(!showEvents)}
              title="Earnings & dividend markers">Events</button>
          )}
          {myLevels.length > 0 && (
            <button className={showMine ? 'active' : ''} aria-pressed={showMine} onClick={() => setShowMine(!showMine)}
              title="Your cost basis, option strikes and price alerts">My levels</button>
          )}
          <button onClick={() => chartRef.current?.timeScale().fitContent()} title="Reset zoom">⟲</button>
        </div>
      </div>

      <div className="indicator-toggles">
        {OVERLAYS.filter(o => !o.intradayOnly || hasVwap).map(o => {
          const on = overlays.includes(o.key);
          return (
            <label key={o.key} className={`indicator-chip ${on ? 'on' : ''}`} style={on ? { borderColor: o.color, color: o.color } : {}}>
              <input type="checkbox" checked={on} onChange={() => toggle(setOverlays)(o.key)} />
              {o.label}
            </label>
          );
        })}
        <span className="chart-divider" />
        {PANELS.map(p => {
          const on = panels.includes(p.key);
          return (
            <label key={p.key} className={`indicator-chip ${on ? 'on' : ''}`}>
              <input type="checkbox" checked={on} onChange={() => toggle(setPanels)(p.key)} />
              {p.label}
            </label>
          );
        })}
        {isIntraday && levels?.levels?.length > 0 && (
          <>
            <span className="chart-divider" />
            {LEVEL_GROUPS.filter(g => levels.levels.some(l => g.keys.includes(l.key))).map(g => {
              const on = levelGroups.includes(g.key);
              return (
                <label key={g.key} className={`indicator-chip ${on ? 'on' : ''}`} style={on ? { borderColor: g.color, color: g.color } : {}}
                  title="Key intraday level (dashed line)">
                  <input type="checkbox" checked={on} onChange={() => toggle(setLevelGroups)(g.key)} />
                  {g.label}
                </label>
              );
            })}
            <Tip term="levels" />
          </>
        )}
      </div>

      <div className="tv-chart-wrap" style={{ height }}>
        <div className="tv-legend">
          <span className="tv-legend-date">{bar.date}</span>
          <span>O <b>{bar.open.toFixed(2)}</b></span>
          <span>H <b>{bar.high.toFixed(2)}</b></span>
          <span>L <b>{bar.low.toFixed(2)}</b></span>
          <span>C <b className={bar.close >= bar.open ? 'positive' : 'negative'}>{bar.close.toFixed(2)}</b></span>
          {chg != null && <span className={chg >= 0 ? 'positive' : 'negative'}>{chg >= 0 ? '+' : ''}{chg.toFixed(2)}%</span>}
          <span>Vol <b>{fmtVol(bars[idx].volume)}</b></span>
          {OVERLAYS.filter(o => overlays.includes(o.key) && !o.keys && bars[idx][o.key] != null).map(o => (
            <span key={o.key} style={{ color: o.color }}>{o.label} {bars[idx][o.key].toFixed(2)}</span>
          ))}
          {panels.includes('rsi') && bars[idx].rsi != null && <span style={{ color: '#e056a0' }}>RSI {bars[idx].rsi.toFixed(1)}</span>}
        </div>
        <div ref={containerRef} className="tv-chart" />
      </div>
    </div>
  );
}
