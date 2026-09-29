const severityStyle = {
  high: { bg: '#d63031', icon: '🔴' },
  warning: { bg: '#e17055', icon: '🟠' },
  medium: { bg: '#fdcb6e', icon: '🟡' },
  info: { bg: '#0984e3', icon: '🔵' },
};

const LABELS = {
  PRICE_CHANGE: 'Big move',
  VOLUME_SPIKE: 'Volume spike',
  NEAR_52W_HIGH: 'Near 52-week high',
  NEAR_52W_LOW: 'Near 52-week low',
  GOLDEN_CROSS: 'Golden cross',
  DEATH_CROSS: 'Death cross',
  ABOVE_200D: 'Reclaimed 200-day',
  BELOW_200D: 'Lost 200-day',
  MACD_BULLISH: 'MACD bullish cross',
  MACD_BEARISH: 'MACD bearish cross',
  RSI_OVERBOUGHT: 'Overbought',
  RSI_OVERSOLD: 'Oversold',
};

export default function Alerts({ alerts }) {
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="alerts-container">
      {alerts.map((a, i) => {
        const style = severityStyle[a.severity] || severityStyle.info;
        return (
          <div key={i} className="alert-banner" style={{ borderLeftColor: style.bg }}>
            <span className="alert-icon">{style.icon}</span>
            <span className="alert-type">{LABELS[a.type] || a.type}</span>
            <span className="alert-message">{a.message}</span>
          </div>
        );
      })}
    </div>
  );
}
