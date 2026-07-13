import { useEffect, useState } from 'react';

export const MOBILE_CONSOLE_QUERY =
  '(max-width: 767px), (max-width: 932px) and (orientation: landscape) and (any-pointer: coarse)';

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
