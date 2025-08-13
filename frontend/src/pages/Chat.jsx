// src/pages/chat.jsx
import ReactMarkdown from 'react-markdown';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import secureAxios from '../utils/secureAxios';

const ACCEPT = [
  '.pdf','.docx','.pptx','.xlsx',
  '.txt','.md','.csv','.json',
  '.jpg','.jpeg','.png'
].join(',');

const iconForExt = (name = '') => {
  const e = (name.split('.').pop() || '').toLowerCase();
  if (['pdf'].includes(e)) return '📄';
  if (['doc','docx'].includes(e)) return '📝';
  if (['ppt','pptx'].includes(e)) return '📊';
  if (['xls','xlsx','csv'].includes(e)) return '📈';
  if (['txt','md','json'].includes(e)) return '📃';
  if (['png','jpg','jpeg'].includes(e)) return '🖼️';
  return '📎';
};
const fmtBytes = (n) => {
  if (!n && n !== 0) return '';
  const u = ['B','KB','MB','GB'];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
};

// --- Chat list helpers: keep active on top & update timestamps ---
const nowISO = () => new Date().toISOString();
const normTime = (c) => new Date(c.updated_at || c.updatedAt || c.created_at || c.createdAt || 0).getTime();

const reorderWithActiveTop = (list, activeId) => {
  const arr = [...(list || [])];
  arr.sort((a, b) => normTime(b) - normTime(a));
  if (!activeId) return arr;
  const idx = arr.findIndex(x => String(x.id) === String(activeId));
  if (idx > 0) {
    const [act] = arr.splice(idx, 1);
    arr.unshift(act);
  }
  return arr;
};

const upsertAndBump = (list, id, patch = {}) => {
  let found = false;
  const bumped = (list || []).map(c => {
    if (String(c.id) === String(id)) {
      found = true;
      return { ...c, ...patch, updated_at: nowISO() };
    }
    return c;
  });
  if (!found) {
    bumped.unshift({
      id,
      title: patch.title || 'New Chat',
      updated_at: nowISO(),
      ...patch,
    });
  }
  return bumped;
};

const Chat = () => {
  const { id: routeId } = useParams();
  const [message, setMessage] = useState('');
  const [chat, setChat] = useState([]);
  const [chatsList, setChatsList] = useState([]);
  const chatEndRef = useRef(null);
  const [isTyping, setIsTyping] = useState(false);
  const [activeChatId, setActiveChatId] = useState(null);

  // rename UI state
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');

  // uploads UI
  const fileInputRef = useRef(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploads, setUploads] = useState([]); // [{id,name,size,progress,status,file}]

  // ---- Fetch chats ----
  const fetchChats = async () => {
    try {
      const res = await secureAxios.get('/chat/sessions');
      const sorted = reorderWithActiveTop(res.data || [], activeChatId);
      setChatsList(sorted);
    } catch (err) {
      console.error('Failed to fetch chats', err);
    }
  };

  // ---- Load a chat thread (memoized) ----
  const loadChat = useCallback(async (chatId) => {
    try {
      const res = await secureAxios.get(`/chat/${chatId}`);
      setChat(res.data);
      setActiveChatId(chatId);
      localStorage.setItem('active_chat_id', String(chatId));
      setEditingId(null);
      setChatsList(prev => reorderWithActiveTop(prev, chatId));
    } catch (err) {
      console.error('Failed to load chat messages:', err);
    }
  }, []);

  // ---- Start a new chat (local reset) ----
  const newChat = () => {
    setActiveChatId(null);
    setChat([]);
    setMessage('');
    setEditingId(null);
  };

  // Ensure a session exists (without polluting chat UI)
  const ensureSession = async () => {
    if (activeChatId) return activeChatId;
    try {
      const res = await secureAxios.post('/chat', { message: ' ' });
      const { session_id, title } = res.data || {};
      if (session_id) {
        setActiveChatId(session_id);
        localStorage.setItem('active_chat_id', String(session_id));
        setChatsList(prev => reorderWithActiveTop(
          upsertAndBump(prev, session_id, { title: title || 'New Chat' }),
          session_id
        ));
        return session_id;
      }
    } catch (e) {
      console.error('Failed to create session for upload:', e);
    }
    return null;
  };

  // ---- Send a message ----
  const send = async () => {
    const text = message.trim();
    if (!text) return;

    setIsTyping(true);
    setChat(prev => [...prev, { role: 'user', content: text }]);
    setMessage('');

    try {
      if (!activeChatId) {
        const res = await secureAxios.post('/chat', { message: text });
        const { session_id, response, title } = res.data || {};
        if (session_id) {
          setActiveChatId(session_id);
          localStorage.setItem('active_chat_id', String(session_id));
          setChatsList(prev => reorderWithActiveTop(
            upsertAndBump(prev, session_id, { title: title || 'New Chat' }),
            session_id
          ));
        }
        setChat(prev => [...prev, { role: 'assistant', content: response ?? '' }]);
      } else {
        const res = await secureAxios.post('/chat', { message: text, session_id: activeChatId });
        const ai = res.data?.response ?? '';
        setChat(prev => [...prev, { role: 'assistant', content: ai }]);
        setChatsList(prev => reorderWithActiveTop(upsertAndBump(prev, activeChatId), activeChatId));
      }
    } catch (err) {
      console.error('Send failed:', err);
    } finally {
      setIsTyping(false);
    }
  };

  // --- Rename handlers ---
  const startEditing = (c) => { setEditingId(c.id); setEditValue(c.title || ''); };
  const cancelEditing = () => { setEditingId(null); setEditValue(''); };
  const saveRename = async () => {
    const id = editingId;
    const title = (editValue || '').trim();
    if (!id) return cancelEditing();
    try {
      setChatsList((list) => list.map(c => String(c.id) === String(id) ? { ...c, title } : c));
      await secureAxios.patch(`/chat/${id}/title`, { title });
      setChatsList(prev => reorderWithActiveTop(prev, activeChatId));
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

  // ---- Uploads ----
  const onClickAttach = () => fileInputRef.current?.click();

  const handleFiles = async (files) => {
    if (!files?.length) return;

    const sid = await ensureSession();
    if (!sid) {
      alert('Could not create a chat session. Please try again.');
      return;
    }

    const items = files.map((f, i) => ({
      id: `${Date.now()}_${i}_${Math.random().toString(36).slice(2,8)}`,
      name: f.name,
      size: f.size,
      progress: 0,
      status: 'queued',
      file: f,
    }));
    setUploads(prev => [...prev, ...items]);

    let ok = 0, fail = 0;

    const tasks = items.map((item) => (async () => {
      try {
        setUploads(prev => prev.map(u => u.id === item.id ? { ...u, status: 'uploading' } : u));
        const fd = new FormData();
        fd.append('session_id', String(sid));
        fd.append('file', item.file);

        await secureAxios.post('/upload', fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
          onUploadProgress: (evt) => {
            if (!evt.total) return;
            const pct = Math.min(99, Math.round((evt.loaded / evt.total) * 100));
            setUploads(prev => prev.map(u => u.id === item.id ? { ...u, progress: pct } : u));
          }
        });

        ok++;
        setUploads(prev => prev.map(u => u.id === item.id ? { ...u, progress: 100, status: 'done' } : u));
      } catch (e) {
        console.error('Upload failed:', e);
        fail++;
        setUploads(prev => prev.map(u => u.id === item.id ? { ...u, status: 'error' } : u));
      }
    })());

    await Promise.all(tasks);

    setChatsList(prev => reorderWithActiveTop(upsertAndBump(prev, sid), sid));

    setTimeout(() => {
      setUploads(prev => prev.filter(u => u.status !== 'done' && u.status !== 'error'));
    }, 600);

    const okText = ok === 1 ? '1 file' : `${ok} files`;
    const failText = fail ? ` (❌ ${fail} failed)` : '';
    const nextSteps = [
      '- Summarize the uploaded content',
      '- Ask for key points or action items',
      '- Search for specific facts, names, or dates',
      '- Compare concepts across documents',
    ].join('\n');

    setChat(prev => [
      ...prev,
      {
        role: 'assistant',
        content:
          `✅ Uploaded ${okText}${failText}.\n\n` +
          `You can now:\n${nextSteps}\n\n` +
          `Try: **"Summarize the key points across the uploaded files."**`
      }
    ]);
  };

  const onFilesChosen = async (e) => {
    const files = Array.from(e.target.files || []);
    await handleFiles(files);
    e.target.value = '';
  };

  const onDragOver = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; };
  const onDragEnter = (e) => { e.preventDefault(); setDragActive(true); };
  const onDragLeave = (e) => {
    if (!e.currentTarget.contains(e.relatedTarget)) setDragActive(false);
  };
  const onDrop = async (e) => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer.files || []);
    await handleFiles(files);
  };

  // ---- INIT: fetch chats; then load by route / saved id ----
  useEffect(() => { fetchChats(); }, []);

  useEffect(() => {
    if (routeId) {
      localStorage.setItem('active_chat_id', String(routeId));
      loadChat(routeId);
    } else {
      const saved = localStorage.getItem('active_chat_id');
      if (saved) loadChat(saved);
    }
  }, [routeId, loadChat]);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chat]);

  return (
    <div className="h-[calc(100vh-56px)] flex bg-gray-50">
      {/* Sidebar */}
      <aside className="w-72 border-r border-gray-200 p-3 flex flex-col bg-white">
        <button
          onClick={newChat}
          className="w-full bg-gradient-to-r from-teal-500 to-indigo-500 text-white px-4 py-2.5 rounded-xl shadow hover:opacity-95 transition mb-3"
        >
          + New Chat
        </button>

        <div className="overflow-y-auto flex-grow pr-1">
          <div className="text-xs text-gray-500 mb-2">Recent chats</div>
          <ul className="space-y-1">
            {reorderWithActiveTop(chatsList, activeChatId).map(c => {
              const isActive = String(c.id) === String(activeChatId);
              return (
                <li key={c.id}>
                  <div
                    className={`p-2 rounded-lg transition group ${
                      isActive
                        ? 'bg-gray-100 border border-gray-300'
                        : 'border border-transparent hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      {editingId === c.id ? (
                        <input
                          className="flex-1 bg-white border rounded px-2 py-1 text-sm"
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onKeyDown={onEditKeyDown}
                          onBlur={saveRename}
                          autoFocus
                          maxLength={80}
                          placeholder="Untitled"
                        />
                      ) : (
                        <button
                          onClick={() => loadChat(c.id)}
                          className={`flex-1 text-left truncate text-sm ${
                            isActive ? 'text-indigo-700 font-medium' : 'text-gray-800'
                          }`}
                          title={c.title}
                        >
                          {c.title || 'Untitled'}
                        </button>
                      )}
                      {editingId !== c.id && (
                        <button
                          className="opacity-0 group-hover:opacity-100 px-2 py-1 rounded hover:bg-gray-200 text-xs"
                          onClick={() => startEditing(c)}
                          title="Rename chat"
                        >
                          ✎
                        </button>
                      )}
                    </div>
                    {(c.updated_at || c.updatedAt || c.created_at || c.createdAt) && (
                      <div className="text-[10px] text-gray-500 mt-0.5">
                        {new Date(c.updated_at || c.updatedAt || c.created_at || c.createdAt).toLocaleString()}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </aside>

      {/* Conversation + Drop zone */}
      <section
        className="flex-1 flex flex-col relative"
        onDragOver={onDragOver}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        {/* Drag overlay */}
        {dragActive && (
          <div className="absolute inset-0 z-20 flex items-center justify-center">
            <div className="pointer-events-none w-[94%] h-[92%] rounded-2xl border-2 border-dashed border-indigo-400 bg-white/70 backdrop-blur-sm flex items-center justify-center">
              <div className="text-sm text-indigo-700 font-medium">Drop files to upload</div>
            </div>
          </div>
        )}

        {/* Sticky header */}
        <div className="sticky top-0 z-10 bg-white/70 backdrop-blur border-b border-gray-200 px-4 py-2 flex items-center justify-between">
          <div className="text-sm font-semibold text-gray-800">
            {(() => {
              const cur = chatsList.find(c => String(c.id) === String(activeChatId));
              return cur?.title || 'New Chat';
            })()}
          </div>
          {/* <div className="flex gap-2">
            <button
              className="text-xs px-2 py-1 rounded-lg border border-gray-200 hover:bg-gray-50"
              onClick={() => window.dispatchEvent(new CustomEvent('export-chat', { detail: { activeChatId } }))}
            >
              Export
            </button>
          </div> */}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {(activeChatId || chat.length > 0) ? (
            <>
              {chat.map((m, i) => {
                const isUser = m.role === 'user';
                return (
                  <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className={`max-w-[75%] p-3 md:p-4 rounded-2xl shadow-sm ${
                        isUser
                          ? 'bg-gradient-to-r from-teal-500 to-indigo-500 text-white rounded-br-md'
                          : 'bg-white text-gray-800 border border-gray-100 rounded-bl-md'
                      }`}
                    >
                      <div className="text-[11px] opacity-80 mb-1">
                        {isUser ? 'You' : 'Neura'}
                      </div>
                      {m.role === 'assistant' ? (
                        <div className={`prose prose-sm ${isUser ? 'prose-invert' : ''}`}>
                          <ReactMarkdown>{m.content}</ReactMarkdown>
                        </div>
                      ) : (
                        <span className="text-sm leading-relaxed">{m.content}</span>
                      )}
                    </div>
                  </div>
                );
              })}
              {isTyping && (
                <div className="flex justify-start">
                  <div className="max-w-[75%] p-3 rounded-2xl bg-white border border-gray-100 text-gray-500 italic">
                    Neura is thinking…
                  </div>
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

        {/* Upload chips (preview + progress) */}
        {uploads.length > 0 && (
          <div className="px-4 pb-2 space-y-2">
            {uploads.map(u => (
              <div
                key={u.id}
                className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm"
              >
                <div className="text-lg">{iconForExt(u.name)}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="truncate text-sm font-medium text-gray-800" title={u.name}>{u.name}</div>
                    <div className="text-xs text-gray-500 shrink-0">{fmtBytes(u.size)}</div>
                    <div className="text-xs ml-auto">
                      {u.status === 'done' && <span className="text-green-600">Done</span>}
                      {u.status === 'error' && <span className="text-red-600">Failed</span>}
                      {u.status === 'uploading' && <span className="text-gray-500">{u.progress}%</span>}
                      {u.status === 'queued' && <span className="text-gray-400">Queued</span>}
                    </div>
                  </div>
                  <div className="mt-1 h-2 w-full rounded bg-gray-200 overflow-hidden">
                    <div
                      className={`h-2 transition-all ${u.status === 'error' ? 'bg-red-500' : 'bg-indigo-500'}`}
                      style={{ width: `${u.status === 'done' ? 100 : u.progress}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Composer */}
        <div className="sticky bottom-0 bg-white border-t border-gray-200 px-4 py-3 z-10">
          <div className="flex gap-2 items-end">
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
              title="Attach files"
              aria-label="Attach files"
              type="button"
              className="p-2.5 rounded-xl border border-gray-300 hover:border-gray-400 hover:bg-gray-50 shadow-sm transition"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
                   fill="none" stroke="currentColor" strokeWidth="1.8"
                   className="h-5 w-5 text-gray-700">
                <path d="M21.44 11.05 12 20.49a6 6 0 1 1-8.49-8.49l9.43-9.44a4.5 4.5 0 1 1 6.36 6.36L9.88 18.35a3 3 0 1 1-4.24-4.24l8.49-8.49" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>

            <textarea
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && message.trim().length > 0) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
              placeholder="Ask about your documents…"
              className="flex-1 resize-none rounded-xl border border-gray-200 bg-white p-3 shadow-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
            />

            <button
              onClick={send}
              disabled={message.trim().length === 0}
              className={`px-4 py-2 rounded-xl text-white shadow transition ${
                message.trim().length > 0
                  ? 'bg-gradient-to-r from-teal-500 to-indigo-500 hover:opacity-95'
                  : 'bg-gray-400 cursor-not-allowed'
              }`}
            >
              Send
            </button>
          </div>
        </div>
      </section>
    </div>
  );
};

export default Chat;


