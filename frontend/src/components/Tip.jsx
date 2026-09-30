import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { GLOSSARY } from '../glossary';

const WIDTH = 260;

// Small "?" that explains a term on hover (desktop) or tap (touch).
// Rendered in a portal because cards use overflow:auto, which would clip it.
export default function Tip({ term, text }) {
  const body = text || GLOSSARY[term];
  const ref = useRef(null);
  const [pos, setPos] = useState(null);

  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    const onKey = e => e.key === 'Escape' && close();
    // iOS doesn't always blur on tap-outside
    const onDown = e => e.target !== ref.current && close();
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    window.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [pos]);

  if (!body) return null;

  const open = () => {
    const r = ref.current.getBoundingClientRect();
    const left = Math.min(Math.max(8, r.left + r.width / 2 - WIDTH / 2), window.innerWidth - WIDTH - 8);
    setPos(r.top > 140 ? { left, top: r.top - 6, above: true } : { left, top: r.bottom + 6, above: false });
  };

  return (
    <>
      <span
        ref={ref}
        className="tip-icon"
        role="button"
        tabIndex={0}
        aria-label={body}
        onPointerEnter={e => e.pointerType === 'mouse' && open()}
        onPointerLeave={e => e.pointerType === 'mouse' && setPos(null)}
        onClick={e => { e.stopPropagation(); e.preventDefault(); open(); }}
        onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), open())}
        onBlur={() => setPos(null)}
      >?</span>
      {pos && createPortal(
        <div role="tooltip" className={`tip-pop ${pos.above ? 'tip-above' : ''}`}
          style={{ left: pos.left, top: pos.top, width: WIDTH }}>
          {body}
        </div>,
        document.body,
      )}
    </>
  );
}
