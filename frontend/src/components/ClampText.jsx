import { useState, useRef, useLayoutEffect } from 'react';

// Clamps long text to a few lines on small screens with a "More" toggle; full text on desktop.
export default function ClampText({ children, className = '' }) {
  const ref = useRef(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, [children]);

  return (
    <div className={className}>
      <p ref={ref} className={`clamp-mobile ${open ? 'open' : ''}`}>{children}</p>
      {(overflows || open) && (
        <button className="clamp-toggle" onClick={() => setOpen(o => !o)}>{open ? 'Less ▴' : 'More ▾'}</button>
      )}
    </div>
  );
}
