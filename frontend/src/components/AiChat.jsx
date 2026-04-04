import { useState, useRef, useEffect } from 'react';
import { sendChat } from '../api/stockApi';

export default function AiChat({ ticker, context }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    setMessages([]);
    setInput('');
    setOpen(false);
  }, [ticker]);

  useEffect(() => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    const userMsg = { role: 'user', content: text };
    const newMsgs = [...messages, userMsg];
    setMessages(newMsgs);
    setInput('');
    setLoading(true);
    try {
      const data = await sendChat(ticker, newMsgs, context);
      setMessages([...newMsgs, { role: 'assistant', content: data.reply }]);
    } catch (e) {
      setMessages([...newMsgs, { role: 'assistant', content: `Error: ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  const suggestions = [
    `What is the bear case for ${ticker}?`,
    `Compare ${ticker} valuation to peers`,
    `What catalysts could move ${ticker} in the next quarter?`,
    `Summarize the revenue growth trend`,
  ];

  return (
    <div className="card ai-chat-card">
      <button className="ai-chat-toggle" onClick={() => setOpen(o => !o)}>
        <span>💬 Ask AI about {ticker}</span>
        <span className="ai-chat-toggle-arrow">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="ai-chat-body">
          {messages.length === 0 && (
            <div className="ai-chat-suggestions">
              {suggestions.map((s, i) => (
                <button key={i} className="suggestion-chip" onClick={() => { setInput(s); }}>
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="ai-chat-messages">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg chat-msg-${m.role}`}>
                <span className="chat-role">{m.role === 'user' ? 'You' : 'AI'}</span>
                <span className="chat-content">{m.content}</span>
              </div>
            ))}
            {loading && (
              <div className="chat-msg chat-msg-assistant">
                <span className="chat-role">AI</span>
                <span className="chat-content loading-text">Thinking…</span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="ai-chat-input-row">
            <input
              className="ai-chat-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
              placeholder={`Ask anything about ${ticker}…`}
              disabled={loading}
            />
            <button className="btn-primary btn-sm" onClick={send} disabled={loading || !input.trim()}>
              Send
            </button>
          </div>

          {messages.length > 0 && (
            <button
              className="ai-chat-clear"
              onClick={() => setMessages([])}
            >
              Clear chat
            </button>
          )}
        </div>
      )}
    </div>
  );
}
