import type { TimelineItem } from '../lib/types';

export function RunTimeline({ items }: { items: TimelineItem[] }) {
  return (
    <section className="card timeline">
      <h2>Run timeline</h2>
      {items.length === 0 ? <p>No events yet.</p> : null}
      <ol>
        {items.map((item) => (
          <li key={item.id}><code>{item.kind}</code> {item.message}</li>
        ))}
      </ol>
    </section>
  );
}
