import { useState, useEffect, useRef } from 'react';
import { searchSymbols } from '../api/stockApi';

const TICKER = /^[A-Za-z][A-Za-z0-9.^=-]{0,9}$/;

export default function SearchBar({ onSearch, loading, activeTicker }) {
  const [query, setQuery] = useState(activeTicker || 'AAPL');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const typed = useRef(false);

  useEffect(() => {
    if (activeTicker) { typed.current = false; setQuery(activeTicker); setOpen(false); }
  }, [activeTicker]);

  useEffect(() => {
    const text = query.trim();
    if (!typed.current || !text) { setResults([]); return undefined; }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchSymbols(text, controller.signal)
        .then(data => { setResults(data.results || []); setHighlight(-1); setOpen(true); })
        .catch(() => setResults([]));
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);

  const choose = (symbol) => {
    typed.current = false;
    setQuery(symbol);
    setOpen(false);
    setResults([]);
    onSearch(symbol.toUpperCase());
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const text = query.trim();
    if (!text) return;
    if (open && highlight >= 0 && results[highlight]) return choose(results[highlight].symbol);
    const exact = results.find(r => r.symbol.toUpperCase() === text.toUpperCase());
    if (exact) return choose(exact.symbol);
    // Lowercase words like "apple" are company searches; an uppercase ticker-shaped entry is taken literally.
    if (results.length && !(TICKER.test(text) && text === text.toUpperCase())) return choose(results[0].symbol);
    choose(text);
  };

  const onKeyDown = (e) => {
    if (!open || !results.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlight(i => (i + 1) % results.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlight(i => (i <= 0 ? results.length - 1 : i - 1)); }
    else if (e.key === 'Escape') { setOpen(false); }
  };

  const showList = open && results.length > 0;
  return (
    <form className="search-bar" onSubmit={handleSubmit} role="search">
      <div className="search-combo">
        <input
          id="ticker-search"
          type="text"
          role="combobox"
          aria-label="Ticker or company name"
          aria-expanded={showList}
          aria-controls="ticker-search-results"
          aria-autocomplete="list"
          aria-activedescendant={showList && highlight >= 0 ? `ticker-option-${highlight}` : undefined}
          autoComplete="off"
          value={query}
          onChange={(e) => { typed.current = true; setQuery(e.target.value); }}
          onKeyDown={onKeyDown}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onFocus={() => results.length && setOpen(true)}
          placeholder="Ticker or company (press / to search)"
          maxLength={40}
        />
        {showList && (
          <ul id="ticker-search-results" role="listbox" className="search-results">
            {results.map((r, i) => (
              <li key={r.symbol} id={`ticker-option-${i}`} role="option" aria-selected={i === highlight}
                className={i === highlight ? 'active' : ''}
                onMouseDown={(e) => { e.preventDefault(); choose(r.symbol); }}>
                <strong>{r.symbol}</strong> <span>{r.name}</span>{r.exchange && <small> · {r.exchange}</small>}
              </li>
            ))}
          </ul>
        )}
      </div>
      <button type="submit" disabled={loading}>
        {loading ? 'Loading...' : 'Analyze'}
      </button>
    </form>
  );
}
