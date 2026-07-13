import { useEffect, useState } from 'react';

export const MOBILE_CONSOLE_QUERY =
  '(max-width: 767px), (max-width: 932px) and (orientation: landscape) and (any-pointer: coarse)';
export const COMPACT_DESKTOP_QUERY = '(min-width: 768px) and (max-width: 1050px)';

function currentLayout(): 'desktop' | 'mobile' {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'desktop';
  return window.matchMedia(MOBILE_CONSOLE_QUERY).matches ? 'mobile' : 'desktop';
}

export function useConsoleLayout(): 'desktop' | 'mobile' {
  const [layout, setLayout] = useState(currentLayout);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia(MOBILE_CONSOLE_QUERY);
    const update = () => setLayout(media.matches ? 'mobile' : 'desktop');
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  return layout;
}

export function useCompactDesktop(): boolean {
  const [compact, setCompact] = useState(() =>
    typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(COMPACT_DESKTOP_QUERY).matches);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia(COMPACT_DESKTOP_QUERY);
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  return compact;
}
