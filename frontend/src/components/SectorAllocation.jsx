import { useState, useEffect, useMemo } from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const COLORS = [
  '#6366f1', '#22d3ee', '#f59e0b', '#ef4444', '#10b981',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4',
  '#84cc16', '#e879f9',
];

function useIsMobile(breakpoint = 600) {
  const [mobile, setMobile] = useState(window.innerWidth <= breakpoint);
  useEffect(() => {
    const handler = () => setMobile(window.innerWidth <= breakpoint);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, [breakpoint]);
  return mobile;
}

export default function SectorAllocation({ holdings }) {
  const isMobile = useIsMobile();

  const sectorData = useMemo(() => {
    if (!holdings?.length) return [];
    const bySector = {};
    holdings.forEach(h => {
      const sector = (h.sector && h.sector !== 'N/A') ? h.sector : 'Unknown';
      const value = (h.current_price || h.buy_price) * h.shares;
      bySector[sector] = (bySector[sector] || 0) + value;
    });
    const total = Object.values(bySector).reduce((a, b) => a + b, 0);
    return Object.entries(bySector)
      .map(([sector, value]) => ({
        sector,
        value: +value.toFixed(2),
        pct: total > 0 ? +((value / total) * 100).toFixed(1) : 0,
      }))
      .sort((a, b) => b.value - a.value);
  }, [holdings]);

  if (!sectorData.length) return null;

  return (
    <div className="glass-card sector-card">
      <h3>🥧 Sector Allocation</h3>
      <div className="sector-chart-wrap">
        <ResponsiveContainer width="100%" height={isMobile ? 220 : 260}>
          <PieChart>
            <Pie
              data={sectorData}
              dataKey="value"
              nameKey="sector"
              cx="50%"
              cy="50%"
              outerRadius={isMobile ? 65 : 90}
              innerRadius={isMobile ? 35 : 50}
              paddingAngle={2}
              label={isMobile ? false : ({ pct }) => `${pct}%`}
              labelLine={false}
            >
              {sectorData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{ background: 'rgba(30,30,50,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#fff' }}
              formatter={(val) => [`$${val.toLocaleString()}`, 'Value']}
            />
            <Legend
              formatter={(value) => <span className="chart-legend-text">{value}</span>}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
