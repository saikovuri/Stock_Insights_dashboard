import { useState } from 'react';

export default function SearchBar({ onSearch, loading }) {
  const [ticker, setTicker] = useState('AAPL');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (ticker.trim()) onSearch(ticker.trim().toUpperCase());
  };

  return (
    <form className="search-bar" onSubmit={handleSubmit}>
      <input
        type="text"
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="Enter ticker (e.g. AAPL)"
        maxLength={10}
      />
      <button type="submit" disabled={loading}>
        {loading ? 'Loading...' : 'Analyze'}
      </button>
    </form>
  );
}
