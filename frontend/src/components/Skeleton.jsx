export default function Skeleton({ label, lines = 3, tiles = 0, chart = false, card = false }) {
  return (
    <div className={`skeleton-block${card ? ' card' : ''}`} aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} aria-hidden="true" className={`skeleton skeleton-line${lines > 1 && i === lines - 1 ? ' short' : ''}`} />
      ))}
      {tiles > 0 && <div className="skeleton-tiles" aria-hidden="true">
        {Array.from({ length: tiles }, (_, i) => <div key={i} className="skeleton skeleton-tile" />)}
      </div>}
      {chart && <div className="skeleton skeleton-chart" aria-hidden="true" />}
    </div>
  );
}
