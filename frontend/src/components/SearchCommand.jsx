// src/components/SearchCommand.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import secureAxios from "../utils/secureAxios";
import { useNavigate } from "react-router-dom";

const useDebounced = (value, ms = 250) => {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
};

export default function SearchCommand({ open, onClose }) {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [res, setRes] = useState({ chats: [], docs: [] });
  const inputRef = useRef(null);
  const panelRef = useRef(null);
  const debounced = useDebounced(q, 250);

  const sessionId = localStorage.getItem("active_chat_id") || "";
  const plan = localStorage.getItem("plan") || "Free";

  // Flatten results for keyboard nav
  const items = useMemo(() => {
    const list = [];
    (res.chats || []).forEach((c) => list.push({ kind: "chat", data: c }));
    (res.docs || []).forEach((d) => list.push({ kind: "doc", data: d }));
    return list;
  }, [res]);

  const [idx, setIdx] = useState(-1);

  // Focus & reset on open
  useEffect(() => {
    if (!open) return;
    setTimeout(() => inputRef.current?.focus(), 0);
    setIdx(-1);
  }, [open]);

  // Close when clicking anywhere outside the panel (backdrop OR page)
  useEffect(() => {
    if (!open) return;
    const onDocDown = (e) => {
      const panel = panelRef.current;
      if (panel && !panel.contains(e.target)) onClose?.();
    };
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, [open, onClose]);

  // Fetch results
  useEffect(() => {
    if (!open) return;
    if (!debounced?.trim()) {
      setRes({ chats: [], docs: [] });
      setIdx(-1);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const { data } = await secureAxios.get("/search", {
          params: { q: debounced, session_id: sessionId, plan },
        });
        if (!cancelled) {
          setRes({
            chats: Array.isArray(data?.chats) ? data.chats : [],
            docs: Array.isArray(data?.docs) ? data.docs : [],
          });
          const total = (data?.chats?.length || 0) + (data?.docs?.length || 0);
          setIdx(total > 0 ? 0 : -1);
        }
      } catch {
        if (!cancelled) {
          setRes({ chats: [], docs: [] });
          setIdx(-1);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [debounced, open, sessionId, plan]);

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (!open) return;
      const keys = ["ArrowDown","ArrowUp","Enter","Escape","Home","End"];
      if (keys.includes(e.key)) e.preventDefault();

      if (e.key === "Escape") return onClose?.();

      if (e.key === "ArrowDown") {
        setIdx((i) => items.length ? (i + 1 + items.length) % items.length : -1);
      } else if (e.key === "ArrowUp") {
        setIdx((i) => items.length ? (i - 1 + items.length) % items.length : -1);
      } else if (e.key === "Home") {
        if (items.length) setIdx(0);
      } else if (e.key === "End") {
        if (items.length) setIdx(items.length - 1);
      } else if (e.key === "Enter") {
        if (idx >= 0 && idx < items.length) openItem(items[idx]);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, items, idx, onClose]);

  // inside SearchCommand.jsx
 // at top

// inside component
const navigate = useNavigate();

const goToChat = (chatId) => {
  if (!chatId) return;
  localStorage.setItem("active_chat_id", String(chatId)); // keep sidebar/other code in sync
  onClose?.();
  navigate(`/chat/${chatId}`); // push a new route → opens that chat
};

const openItem = (item) => {
  if (!item) return;
  if (item.kind === "chat") {
    goToChat(item.data.chat_id);
  } else {
    // doc result may or may not have chat_id; fall back to current
    const fallback = localStorage.getItem("active_chat_id") || "";
    goToChat(item.data.chat_id || fallback);
  }
};

  if (!open) return null;

  return (
    // Backdrop — also closes on click
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center p-4 sm:p-6 bg-black/40"
      onMouseDown={(e) => {
        // If you click the backdrop (not the panel), close
        if (e.target === e.currentTarget) onClose?.();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Search"
    >
      <div
        ref={panelRef}
        className="w-full max-w-2xl rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xl overflow-hidden"
      >
        <div className="p-3 border-b border-zinc-200 dark:border-zinc-800">
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search chats & documents…"
            className="w-full bg-transparent outline-none text-sm px-2 py-2"
            aria-label="Search query"
          />
        </div>

        {loading && <div className="p-3 text-sm text-zinc-500">Searching…</div>}

        {!loading && !q && (
          <div className="p-3 text-sm text-zinc-500">
            Type to search your chat titles, messages, and documents. Use ↑/↓ and Enter.
          </div>
        )}

        {!loading && q && (
          <div className="max-h-[60vh] overflow-auto p-2 sm:p-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Chats */}
            <section aria-label="Chats">
              <h4 className="px-2 pb-2 text-xs uppercase tracking-wide text-zinc-500">Chats</h4>
              <ul className="space-y-1">
                {(res.chats || []).length === 0 && (
                  <li className="px-2 py-2 text-xs text-zinc-500">No matches.</li>
                )}
                {(res.chats || []).map((c, i) => {
                  const flatIndex = i; // chats first
                  const active = idx === flatIndex;
                  return (
                    <li
                      key={`${c.id || c.chat_id}-c`}
                      className={`px-2 py-2 rounded-lg cursor-pointer ${
                        active ? "bg-zinc-100 dark:bg-zinc-800" : "hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      }`}
                      onMouseEnter={() => setIdx(flatIndex)}
                      onClick={() => openItem({ kind: "chat", data: c })}
                      role="option"
                      aria-selected={active}
                    >
                      <div className="text-sm font-medium truncate">{c.title || c.preview}</div>
                      {c.preview && <div className="text-xs text-zinc-500 truncate">{c.preview}</div>}
                    </li>
                  );
                })}
              </ul>
            </section>

            {/* Documents */}
            <section aria-label="Documents">
              <h4 className="px-2 pb-2 text-xs uppercase tracking-wide text-zinc-500">Documents</h4>
              <ul className="space-y-1">
                {(res.docs || []).length === 0 && (
                  <li className="px-2 py-2 text-xs text-zinc-500">No matches.</li>
                )}
                {(res.docs || []).map((d, i) => {
                  const flatIndex = (res.chats?.length || 0) + i;
                  const active = idx === flatIndex;
                  return (
                    <li
                      key={`${d.id || d.chunk_id || d.filename}-d`}
                      className={`px-2 py-2 rounded-lg cursor-pointer ${
                        active ? "bg-zinc-100 dark:bg-zinc-800" : "hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      }`}
                      onMouseEnter={() => setIdx(flatIndex)}
                      onClick={() => openItem({ kind: "doc", data: d })}
                      role="option"
                      aria-selected={active}
                    >
                      <div className="text-sm font-medium truncate">{d.filename || d.source || "Document"}</div>
                      <div className="text-xs text-zinc-500 truncate">{d.snippet || ""}</div>
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>
        )}

        <div className="p-2 border-t border-zinc-200 dark:border-zinc-800 text-[11px] text-right text-zinc-500">
          ↑/↓ to navigate • Enter to open • Esc to close
        </div>
      </div>
    </div>
  );
}
