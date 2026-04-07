import { useMemo } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

export default function PortfolioChart({ holdings, closedTrades }) {
  // Build a simple portfolio value timeline from closed trades + current holdings
  const chartData = useMemo(() => {
    if (!holdings?.length && !closedTrades?.trades?.length) return [];

    // Timeline approach: aggregate current holding values as "today"
    const totalCurrent = holdings?.reduce((s, h) =>
      s + (h.current_price || h.buy_price) * h.shares, 0) || 0;
    const totalInvested = holdings?.reduce((s, h) =>
      s + h.buy_price * h.shares, 0) || 0;

    // Build data from closed trades (realized P&L events)
    const events = [];
    let runningInvested = totalInvested;
    let runningPnl = 0;

    // If we have closed trades, show P&L progression
    if (closedTrades?.trades?.length) {
      const sorted = [...closedTrades.trades].sort((a, b) =>
        (a.sold_at || a.date || '').localeCompare(b.sold_at || b.date || '')
      );
      sorted.forEach(t => {
        runningPnl += (t.pnl || 0);
        events.push({
          date: t.sold_at || t.date || 'Unknown',
          realized_pnl: +runningPnl.toFixed(2),
        });
      });
    }

    // Add current portfolio as today
    const today = new Date().toISOString().slice(0, 10);
    const totalPnl = (totalCurrent - totalInvested) + (closedTrades?.total_realized_pnl || 0);

    // Simple chart: if no closed trades, show invest vs current
    if (!events.length) {
      if (!holdings?.length) return [];
      return [
        { date: 'Invested', value: +totalInvested.toFixed(2) },
        { date: 'Current', value: +totalCurrent.toFixed(2) },
      ];
    }

    // Add today's snapshot
    events.push({
      date: today,
      realized_pnl: +(runningPnl + (totalCurrent - totalInvested)).toFixed(2),
    });

    return events;
  }, [holdings, closedTrades]);

  if (!chartData.length) return null;

  const isSimple = chartData[0]?.value != null; // invest vs current mode
  const dataKey = isSimple ? 'value' : 'realized_pnl';
  const lastVal = chartData[chartData.length - 1]?.[dataKey] || 0;
  const firstVal = chartData[0]?.[dataKey] || 0;
  const isUp = lastVal >= firstVal;

  return (
    <div className="glass-card portfolio-chart-card">
      <h3>📈 Portfolio Performance</h3>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="pf-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={isUp ? '#00c853' : '#ef5350'} stopOpacity={0.3} />
              <stop offset="100%" stopColor={isUp ? '#00c853' : '#ef5350'} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" tick={{ fill: 'var(--chart-text, #b0b8c8)', fontSize: 10 }} />
          <YAxis tick={{ fill: 'var(--chart-text, #b0b8c8)', fontSize: 11 }} tickFormatter={v => `$${v.toLocaleString()}`} width={70} />
          <Tooltip
            contentStyle={{ background: 'rgba(30,30,50,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#fff' }}
            formatter={(v) => [`$${v.toLocaleString()}`, isSimple ? 'Value' : 'Cumulative P&L']}
          />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={isUp ? '#00c853' : '#ef5350'}
            fill="url(#pf-grad)"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
