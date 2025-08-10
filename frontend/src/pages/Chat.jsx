// chat.jsx
import ReactMarkdown from 'react-markdown';
import React, { useState, useEffect, useRef } from 'react';
import secureAxios from '../utils/secureAxios';

const ACCEPT = [
  '.pdf','.docx','.pptx','.xlsx',
  '.txt','.md','.csv',
  '.jpg','.jpeg','.png'
].join(',');

const Chat = () => {
  const [message, setMessage] = useState('');
  const [chat, setChat] = useState([]);
  const [chatsList, setChatsList] = useState([]);
  const chatEndRef = useRef(null);
  const [isTyping, setIsTyping] = useState(false);
  const [activeChatId, setActiveChatId] = useState(null);

  // rename UI state
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');

  const fileInputRef = useRef(null);

  const fetchChats = async () => {
    try {
      const res = await secureAxios.get('/chat/sessions');
      setChatsList(res.data);
    } catch (err) {
      console.error('Failed to fetch chats', err);
    }
  };

  const loadChat = async (chatId) => {
    try {
      const res = await secureAxios.get(`/chat/${chatId}`);
      setChat(res.data);
      setActiveChatId(chatId);
      setEditingId(null);
    } catch (err) {
      console.error('Failed to load chat messages:', err);
    }
  };

  const newChat = async () => {
    setActiveChatId(null);
    setChat([]);
    setMessage('');
    setEditingId(null);
  };

  // Ensure a session exists (without polluting chat UI)
  const ensureSession = async () => {
    if (activeChatId) return activeChatId;
    try {
      // create a session with a blank first message
      const res = await secureAxios.post('/chat', { message: ' ' });
      const { session_id } = res.data || {};
      if (session_id) {
        setActiveChatId(session_id);
        fetchChats();
        return session_id;
      }
    } catch (e) {
      console.error('Failed to create session for upload:', e);
    }
    return null;
  };

  const send = async () => {
    const text = message.trim();
    if (!text) return;

    setIsTyping(true);
    setChat(prev => [...prev, { role: 'user', content: text }]);
    setMessage('');

    try {
      if (!activeChatId) {
        const res = await secureAxios.post('/chat', { message: text });
        const { session_id, response } = res.data || {};
        if (session_id) {
          setActiveChatId(session_id);
          fetchChats();
        }
        setChat(prev => [...prev, { role: 'assistant', content: response ?? '' }]);
      } else {
        const res = await secureAxios.post('/chat', { message: text, session_id: activeChatId });
        const ai = res.data?.response ?? '';
        setChat(prev => [...prev, { role: 'assistant', content: ai }]);
      }
    } catch (err) {
      console.error('Send failed:', err);
    } finally {
      setIsTyping(false);
    }
  };

  // --- Rename handlers (unchanged) ---
  const startEditing = (chat) => { setEditingId(chat.id); setEditValue(chat.title || ''); };
  const cancelEditing = () => { setEditingId(null); setEditValue(''); };
  const saveRename = async () => {
    const id = editingId;
    const title = (editValue || '').trim();
    if (!id) return cancelEditing();
    try {
      setChatsList((list) => list.map(c => c.id === id ? { ...c, title } : c));
      await secureAxios.patch(`/chat/${id}/title`, { title });
    } catch (err) {
      console.error('Rename failed:', err);
      fetchChats();
    } finally {
      cancelEditing();
    }
  };
  const onEditKeyDown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); saveRename(); }
    else if (e.key === 'Escape') { e.preventDefault(); cancelEditing(); }
  };

  // ---- File upload handler ----
  const onClickAttach = () => fileInputRef.current?.click();

  const onFilesChosen = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    const sid = await ensureSession();
    if (!sid) {
      alert('Could not create a chat session. Please try again.');
      return;
    }

    for (const file of files) {
      try {
        const fd = new FormData();
        fd.append('session_id', String(sid));
        fd.append('file', file);
        const res = await secureAxios.post('/upload', fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });

        // Show a lightweight system bubble for UX
        setChat(prev => [
          ...prev,
          { role: 'assistant', content: `📎 Indexed **${file.name}** (${res.data?.chars_indexed ?? 0} chars). You can now ask questions about it.` }
        ]);
      } catch (err) {
        console.error('Upload failed:', err);
        setChat(prev => [
          ...prev,
          { role: 'assistant', content: `⚠️ Failed to upload **${file.name}**` }
        ]);
      }
    }

    // clear input so selecting the same file again triggers change
    e.target.value = '';
  };

  useEffect(() => { fetchChats(); }, []);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chat]);

  return (
    <div className="flex h-[calc(100vh-60px)]">
      {/* Left Pane (unchanged) */}
      <div className="w-1/4 bg-white border-r p-4 flex flex-col">
        <button onClick={newChat} className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 mb-4">
          + New Chat
        </button>

        <div className="overflow-y-auto flex-grow">
          <h2 className="text-lg font-semibold mb-2">Chats</h2>
          <ul className="space-y-2">
            {activeChatId && (
              <li className="p-2 bg-green-100 rounded font-semibold text-green-900 border border-green-300">
                🟢 {chatsList.find(c => c.id === activeChatId)?.title || 'Current Chat'}
              </li>
            )}

            {chatsList
              .filter(c => c.id !== activeChatId)
              .map(c => (
                <li key={c.id} className="p-2 bg-gray-100 rounded hover:bg-gray-200 group">
                  <div className="flex items-center gap-2">
                    {editingId === c.id ? (
                      <input
                        className="flex-1 bg-white border rounded px-2 py-1"
                        value={editValue}
                        onChange={e => setEditValue(e.target.value)}
                        onKeyDown={onEditKeyDown}
                        onBlur={saveRename}
                        autoFocus
                        maxLength={80}
                        placeholder="Untitled"
                      />
                    ) : (
                      <button onClick={() => loadChat(c.id)} className="flex-1 text-left truncate" title={c.title}>
                        {c.title}
                      </button>
                    )}
                    {editingId !== c.id && (
                      <button
                        className="opacity-0 group-hover:opacity-100 px-2 py-1 rounded hover:bg-gray-300"
                        onClick={() => startEditing(c)}
                        title="Rename chat"
                      >
                        ✎
                      </button>
                    )}
                  </div>
                </li>
              ))}
          </ul>
        </div>
      </div>

      {/* Right Pane */}
      <div className="flex-1 flex flex-col bg-gray-50">
        <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
          {(activeChatId || chat.length > 0) ? (
            <>
              {chat.map((m, i) => (
                <div
                  key={i}
                  className={`p-3 rounded max-w-xl ${m.role === 'user' ? 'bg-blue-100 self-end' : 'bg-gray-200 self-start'}`}
                >
                  <strong>{m.role === 'user' ? 'You' : 'Neura'}:</strong>{' '}
                  {m.role === 'assistant' ? (
                    <div className="prose prose-sm"><ReactMarkdown>{m.content}</ReactMarkdown></div>
                  ) : (
                    <span>{m.content}</span>
                  )}
                </div>
              ))}
              {isTyping && (
                <div className="p-3 rounded max-w-xl bg-gray-200 self-start italic text-gray-500">
                  Neura is thinking...
                </div>
              )}
              <div ref={chatEndRef} />
            </>
          ) : (
            <div className="text-center text-gray-500 mt-10 text-lg italic">
              👋 Start typing below or click <strong>+ New Chat</strong>.
            </div>
          )}
        </div>

        {/* Input Row with Attach */}
        <div className="sticky bottom-0 bg-gray-50 px-4 py-3 border-t flex gap-2 items-center">
          <input
            value={message}
            onChange={e => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && message.trim().length > 0) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask something..."
            className="flex-1 p-2 border rounded"
          />
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            accept={ACCEPT}
            multiple
            onChange={onFilesChosen}
          />
          <button
            onClick={onClickAttach}
            className="px-3 py-2 border rounded hover:bg-gray-100"
            title="Attach files"
          >
            📎
          </button>
          <button
            onClick={send}
            disabled={message.trim().length === 0}
            className={`px-4 py-2 text-white rounded ${message.trim().length > 0 ? 'bg-blue-600 hover:bg-blue-700' : 'bg-gray-400 cursor-not-allowed'}`}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
};

export default Chat;
