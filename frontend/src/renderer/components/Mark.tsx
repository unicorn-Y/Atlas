/** Atlas brand mark: glass sphere with brass orbit rings. Render <MarkDefs/> once at the app root. */
export function MarkDefs() {
  return <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
    <defs>
      <radialGradient id="gm-glass" cx="38%" cy="32%" r="75%"><stop offset="0" stopColor="#fff" /><stop offset=".45" stopColor="#E9EEF7" /><stop offset="1" stopColor="#B9C6DE" /></radialGradient>
      <linearGradient id="gm-brass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#D9AE6C" /><stop offset="1" stopColor="#8E5F24" /></linearGradient>
    </defs>
    <symbol id="atlas-mark" viewBox="0 0 32 32">
      <circle cx="16" cy="16" r="11.5" fill="url(#gm-glass)" stroke="rgba(27,34,50,.18)" strokeWidth=".8" />
      <ellipse cx="16" cy="16" rx="15" ry="5.2" fill="none" stroke="url(#gm-brass)" strokeWidth="1.5" transform="rotate(-24 16 16)" />
      <ellipse cx="16" cy="16" rx="5.2" ry="15" fill="none" stroke="url(#gm-brass)" strokeWidth="1" opacity=".7" transform="rotate(-24 16 16)" />
      <circle cx="12.3" cy="11.8" r="2.4" fill="#fff" opacity=".9" />
    </symbol>
  </svg>;
}

export default function Mark({ className = 'mark' }: { className?: string }) {
  return <svg className={className} aria-hidden="true"><use href="#atlas-mark" /></svg>;
}
