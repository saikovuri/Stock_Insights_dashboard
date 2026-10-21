import { useUiMode } from '../uiMode';

export function ModeToggle() {
  const { simple, setMode } = useUiMode();
  return <div className="mode-toggle" role="group" aria-label="Interface mode"
    title="Simple hides specialist and overlapping tools; Advanced shows everything">
    <button type="button" className={simple ? 'active' : ''} aria-pressed={simple} onClick={() => setMode('simple')}>Simple</button>
    <button type="button" className={simple ? '' : 'active'} aria-pressed={!simple} aria-label="Advanced" onClick={() => setMode('advanced')}>
      <span className="mode-long">Advanced</span><span className="mode-short" aria-hidden="true">Adv</span>
    </button>
  </div>;
}

/** Tells the user what Simple mode hides here, with a one-click way to see it. */
export function SimpleNote({ names }) {
  const { simple, setMode } = useUiMode();
  if (!simple || !names.length) return null;
  return <p className="simple-note">
    Simple mode hides {names.length} more: {names.join(', ')}.{' '}
    <button type="button" className="link-btn" onClick={() => setMode('advanced')}>Show advanced</button>
  </p>;
}
