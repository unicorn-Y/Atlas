import { cn } from '../ui/cn';

/**
 * Atlas brand mark: a line-drawn armillary sphere in brass.
 * `working` turns its rings — the app's single signature motion, shown only while Atlas is busy.
 * Render <MarkDefs/> once at the app root; marks reference its symbols.
 */
export function MarkDefs() {
  return <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
    <defs>
      {/* Stop colours come from the theme (--mark-*, --core-*): brass in 夜航/白瓷, periwinkle in 晨光. */}
      <linearGradient id="atlas-brass" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" style={{ stopColor: 'var(--mark-1)' }} /><stop offset=".55" style={{ stopColor: 'var(--mark-2)' }} /><stop offset="1" style={{ stopColor: 'var(--mark-3)' }} />
      </linearGradient>
      <radialGradient id="atlas-core" cx="40%" cy="35%" r="70%">
        <stop offset="0" style={{ stopColor: 'var(--core-1)' }} /><stop offset="1" style={{ stopColor: 'var(--core-2)' }} />
      </radialGradient>
    </defs>
  </svg>;
}

export default function Mark({ className, working = false }: { className?: string; working?: boolean }) {
  return <svg viewBox="0 0 48 48" className={cn('size-7 shrink-0', working && 'arm-working', className)} aria-hidden="true">
    <circle cx="24" cy="24" r="20.5" fill="none" stroke="url(#atlas-brass)" strokeWidth="1.7" />
    <g className="arm-r1"><ellipse cx="24" cy="24" rx="20.5" ry="7" fill="none" stroke="url(#atlas-brass)" strokeWidth="1.7" transform="rotate(-23.5 24 24)" /></g>
    <g className="arm-r2"><ellipse cx="24" cy="24" rx="7.5" ry="20.5" fill="none" stroke="url(#atlas-brass)" strokeWidth="1.2" opacity=".8" /></g>
    <circle cx="24" cy="24" r="4.8" fill="url(#atlas-core)" />
  </svg>;
}

/** Large decorative armillary drawn behind the home greeting in the dark theme. */
export function Orb({ className }: { className?: string }) {
  return <svg viewBox="0 0 400 400" className={className} aria-hidden="true">
    <g fill="none" stroke="url(#atlas-brass)">
      <circle cx="200" cy="200" r="170" strokeWidth="1.2" />
      <circle cx="200" cy="200" r="158" strokeWidth=".5" opacity=".6" />
      <g strokeWidth=".8" opacity=".7">
        <path d="M200 30v10M200 360v10M30 200h10M360 200h10" />
        <path d="M320 80l-7 7M80 320l7-7M80 80l7 7M320 320l-7-7" opacity=".7" />
      </g>
      <ellipse cx="200" cy="200" rx="170" ry="58" strokeWidth="1.4" transform="rotate(-23.5 200 200)" />
      <ellipse cx="200" cy="200" rx="170" ry="30" strokeWidth=".6" opacity=".55" />
      <ellipse cx="200" cy="200" rx="62" ry="170" strokeWidth="1" opacity=".75" />
      <ellipse cx="200" cy="200" rx="120" ry="170" strokeWidth=".5" opacity=".45" />
      <circle cx="200" cy="200" r="36" strokeWidth=".6" opacity=".5" />
    </g>
    <circle cx="200" cy="200" r="22" fill="url(#atlas-core)" opacity=".9" />
    <circle cx="352" cy="132" r="4" style={{ fill: 'var(--mark-1)' }} />
  </svg>;
}
