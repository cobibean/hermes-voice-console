import { useEffect, useState } from 'react';

export function StatusAnnouncer({ status }: { status: string }) {
  const [announced, setAnnounced] = useState(status);
  useEffect(() => {
    const timer = window.setTimeout(() => setAnnounced(status.replaceAll('_', ' ')), 500);
    return () => window.clearTimeout(timer);
  }, [status]);
  return <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{announced}</p>;
}
