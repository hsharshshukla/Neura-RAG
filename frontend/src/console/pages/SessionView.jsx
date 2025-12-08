// src/console/pages/SessionView.jsx
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { fetchJSON } from "../../lib/fetchJSON";

function Bubble({ role = "user", content = "", created_at }) {
  const r = String(role || "").toLowerCase();
  const isUser = r === "user";
  const isAssistant = r === "assistant" || r === "model" || r === "bot";
  const align = isUser ? "justify-start" : "justify-end";

  return (
    <div className={`flex ${align} my-2`}>
      <div
        className={`max-w-[75%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
          isUser
            ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
            : "bg-indigo-600 text-white dark:bg-indigo-500"
        }`}
      >
        {content || "—"}
        <div className={`mt-1 text-[10px] opacity-70 ${isAssistant ? "text-white" : "text-zinc-600"}`}>
          {created_at ? new Date(created_at).toLocaleString() : ""}
        </div>
      </div>
    </div>
  );
}

export default function SessionView() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const scrollerRef = useRef(null);

  const scrollToBottom = () => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  const normalizeMessage = (m) => {
    if (!m) return null;
    const roleRaw = m.role || m.sender || m.author || "user";
    const role = String(roleRaw).toLowerCase();
    const content = m.content ?? m.text ?? m.message ?? "";
    const created_at = m.created_at ?? m.timestamp ?? null;
    const id = m.id ?? `${created_at || ""}-${role}-${Math.random().toString(36).slice(2, 7)}`;
    return { id, role, content, created_at };
  };

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const d = await fetchJSON(`/api/v1/admin/sessions/${encodeURIComponent(id)}`);
      setSession(d?.session || null);
      const normalized = (d?.messages || [])
        .map(normalizeMessage)
        .filter(Boolean);
      setMessages(normalized);
      // Scroll after paint
      setTimeout(scrollToBottom, 0);
    } catch (e) {
      setSession(null);
      setMessages([]);
      setErr(e?.message || "Failed to load session");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [id]);

  const title = useMemo(() => {
    if (!session) return `Session ${id}`;
    const email = session.user_email || session.user?.email || "";
    return email ? `${email} — ${id}` : `Session ${id}`;
  }, [session, id]);

  const messageCount = messages.length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Session</h2>
          <div className="text-sm text-zinc-500">{title}</div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate(-1)}
            className="px-3 py-2 rounded border"
            title="Back"
          >
            ← Back
          </button>
          <button
            onClick={load}
            className="px-3 py-2 rounded border"
            disabled={loading}
            title="Refresh transcript"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {err && (
        <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 text-sm px-3 py-2">
          {err}
        </div>
      )}

      {/* Session meta */}
      {session && (
        <div className="rounded-xl border p-4 bg-white dark:bg-zinc-900">
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <div className="text-zinc-500">User</div>
              <div className="font-medium break-all">
                {session.user_email || session.user?.email || "—"}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Created</div>
              <div className="font-medium">
                {session.created_at ? new Date(session.created_at).toLocaleString() : "—"}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Messages</div>
              <div className="font-medium">{messageCount}</div>
            </div>
            <div>
              <div className="text-zinc-500">Session ID</div>
              <div className="font-mono text-xs break-all">{id}</div>
            </div>
          </div>
        </div>
      )}

      {/* Transcript (read-only) */}
      <div
        ref={scrollerRef}
        className="rounded-xl border p-4 bg-white dark:bg-zinc-900 min-h-[50vh] max-h-[70vh] overflow-y-auto"
      >
        {loading && !messages.length ? (
          <div className="text-sm text-zinc-500">Loading…</div>
        ) : !messages.length ? (
          <div className="text-sm text-zinc-500">No messages found.</div>
        ) : (
          messages.map((m) => (
            <Bubble
              key={m.id}
              role={m.role}
              content={m.content}
              created_at={m.created_at}
            />
          ))
        )}
      </div>

      <div className="text-xs text-zinc-500">
        Read-only viewer. You are <span className="font-medium">not</span> impersonating the user.
      </div>
    </div>
  );
}
