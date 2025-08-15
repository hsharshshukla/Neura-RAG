// ============================
// File: src/sections/admin/pages/Sessions.jsx
// ============================
import { useEffect, useState } from 'react';
import secureAxios from '../../../utils/secureAxios';
import Card from '../components/Card';

export default function Sessions() {
  const [rows, setRows] = useState([]);
  const [sid, setSid] = useState('');
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await secureAxios.get('/admin/sessions', { params: { sid, limit: 20 } });
        setRows(data.items || []);
      } catch { setRows([]); }
    })();
  }, [sid]);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <Card title="Chat Sessions" action={<div className="flex items-center gap-2"><input value={sid} onChange={(e)=>setSid(e.target.value)} className="text-sm border rounded-lg px-2 py-1" placeholder="Filter by Session ID…" /></div>}>
        <div className="overflow-hidden rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>{['Session','User','Started','Messages'].map(h=> <th key={h} className="text-left px-3 py-2 font-medium text-gray-600">{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-t hover:bg-gray-50 cursor-pointer" onClick={() => setSelected(s)}>
                  <td className="px-3 py-2">{s.session_id}</td>
                  <td className="px-3 py-2 text-gray-500">{s.user_email}</td>
                  <td className="px-3 py-2">{s.created_at ? new Date(s.created_at).toISOString().slice(0,10) : '-'}</td>
                  <td className="px-3 py-2">{s.message_count ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Transcript">
        <div className="rounded-xl border p-4 text-sm text-gray-700 h-72 overflow-auto">
          {selected ? <pre className="whitespace-pre-wrap">{selected.transcript || 'No transcript available'}</pre> : <div className="h-full flex items-center justify-center text-gray-400">Select a session to view transcript</div>}
        </div>
      </Card>
    </div>
  );
}
