const severityStyle = {
  high: { bg: '#d63031', icon: '🔴' },
  warning: { bg: '#e17055', icon: '🟠' },
  medium: { bg: '#fdcb6e', icon: '🟡' },
  info: { bg: '#0984e3', icon: '🔵' },
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
            <span className="alert-type">{a.type}</span>
            <span className="alert-message">{a.message}</span>
          </div>
        );
      })}
    </div>
  );
}
