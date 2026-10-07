import { useEffect, useRef, useState } from 'react';

/** Sub-tab strip that scrolls sideways when the tabs don't fit, with fade edges and arrow buttons instead of a scrollbar. */
export default function TabStrip({ label, activeKey, children }) {
  const strip = useRef(null);
  const [edges, setEdges] = useState({ left: false, right: false });

  useEffect(() => {
    const element = strip.current;
    const update = () => setEdges({
      left: element.scrollLeft > 1,
      right: element.scrollLeft + element.clientWidth < element.scrollWidth - 1,
    });
    update();
    element.addEventListener('scroll', update, { passive: true });
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    observer?.observe(element);
    return () => { element.removeEventListener('scroll', update); observer?.disconnect(); };
  }, []);

  useEffect(() => {
    const element = strip.current;
    const active = element.querySelector('.sub-tab.active');
    if (!active || element.scrollWidth <= element.clientWidth) return;
    const left = active.offsetLeft - (element.clientWidth - active.offsetWidth) / 2;
    element.scrollTo?.({ left: Math.max(0, left), behavior: 'smooth' });
  }, [activeKey]);

  const page = direction => strip.current.scrollBy?.({ left: direction * strip.current.clientWidth * 0.7, behavior: 'smooth' });

  return (
    <div className={`tab-strip${edges.left ? ' fade-left' : ''}${edges.right ? ' fade-right' : ''}`}>
      {edges.left && <button type="button" className="tab-strip-arrow left" aria-hidden="true" tabIndex={-1} onClick={() => page(-1)}>‹</button>}
      <nav ref={strip} className="sub-tabs" aria-label={label}>{children}</nav>
      {edges.right && <button type="button" className="tab-strip-arrow right" aria-hidden="true" tabIndex={-1} onClick={() => page(1)}>›</button>}
    </div>
  );
}
