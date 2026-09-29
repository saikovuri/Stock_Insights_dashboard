import { useState, useRef, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { sendChat } from '../api/stockApi';

const TOOL_LABELS = {
  get_stock_snapshot: 'quote & technicals',
  get_news: 'news',
  get_analyst_view: 'analysts',
  get_fundamentals: 'fundamentals',
  get_sec_filings: 'SEC filings',
  get_peers: 'peers',
  get_my_portfolio: 'your portfolio',
};

export default function AiChat({ ticker, onSignIn }) {
  const { user } = useAuth();
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
      // Only role/content go to the server; tool metadata stays client-side
      const data = await sendChat(ticker, newMsgs.map(({ role, content }) => ({ role, content })).slice(-20));
      setMessages([...newMsgs, { role: 'assistant', content: data.reply, tools: data.tools_used }]);
    } catch (e) {
      setMessages([...newMsgs, { role: 'assistant', content: `Error: ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  const suggestions = [
    `What is the bear case for ${ticker}?`,
    `Compare ${ticker} valuation to peers`,
    `Any insider trades or recent SEC filings for ${ticker}?`,
    `How would adding ${ticker} change my portfolio's risk?`,
  ];

  if (!user) {
    return (
      <div className="card ai-chat-card">
        <h3>💬 Ask AI about {ticker}</h3>
        <p className="empty-state">Sign in to chat with an AI analyst that pulls live quotes, news, filings and your portfolio.</p>
        {onSignIn && <button className="btn-primary btn-sm" onClick={onSignIn}>Sign in</button>}
      </div>
    );
  }

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
                {m.tools?.length > 0 && (
                  <span className="chat-tools">
                    Used: {[...new Set(m.tools)].map(t => TOOL_LABELS[t] || t).join(', ')}
                  </span>
                )}
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
