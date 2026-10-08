/** When option ideas were priced; provider quotes (and the 3–5 minute server cache) can make them a few minutes older. */
export default function PricedAt({ asOf }) {
  if (!asOf) return null;
  const time = new Date(asOf).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  return <span title="Option quotes are cached for a few minutes and can be delayed by the data provider"> · priced {time}</span>;
}
