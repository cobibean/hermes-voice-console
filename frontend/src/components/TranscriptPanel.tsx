import type { ConversationMessage } from '../lib/types';

export function TranscriptPanel({
  messages,
  response,
}: {
  messages: ConversationMessage[];
  response: string;
}) {
  return (
    <section className="card conversation-history" aria-label="Conversation messages">
      <h2>Conversation</h2>
      <div className="message-list">
        {messages.length === 0 && !response ? <p className="empty-history">No messages yet.</p> : null}
        {messages.map((message, index) => (
          <article className={`message ${message.role}`} key={message.id ?? `${index}-${message.content.slice(0, 24)}`}>
            <strong>{message.role === 'user' ? 'You' : message.role === 'tool' ? `Tool · ${message.tool ?? 'Hermes'}` : 'Hermes'}</strong>
            <p>{message.content}</p>
            {message.role === 'tool' ? (
              <small className={`tool-status ${message.status ?? 'completed'}`} role="status" aria-live="polite">
                {message.status ?? 'completed'}
                {typeof message.duration === 'number' ? ` · ${message.duration.toFixed(2)}s` : ''}
              </small>
            ) : null}
          </article>
        ))}
        {response ? (
          <article className="message assistant streaming">
            <strong>Hermes</strong>
            <p>{response}</p>
          </article>
        ) : null}
      </div>
    </section>
  );
}
