// ============================
// File: src/sections/admin/pages/Files.jsx
// ============================
import { useEffect, useState } from 'react';
import secureAxios from '../../../utils/secureAxios';
import Card from '../components/Card';

export default function Files() {
  const [rows, setRows] = useState([]);
  const [type, setType] = useState('');
  const [q, setQ] = useState('');
  const [stats, setStats] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await secureAxios.get('/admin/uploads', { params: { q, type, limit: 20, offset: 0 } });
        setRows(data.items || []);
        setStats(data.stats || null);
      } catch { setRows([]); setStats(null); }
    })();
  }, [type, q]);

  return (
    <div className="space-y-4">
      <Card title="Recent Uploads" action={
        <div className="flex items-center gap-2">
          <select value={type} onChange={(e) => setType(e.target.value)} className="text-sm border rounded-lg px-2 py-1">
            <option value="">All types</option>
            <option value="pdf">PDF</option>
            <option value="docx">DOCX</option>
            <option value="image">Images</option>
            <option value="txt">TXT</option>
          </select>
          <input value={q} onChange={(e) => setQ(e.target.value)} className="text-sm border rounded-lg px-2 py-1" placeholder="Search…" />
        </div>
      }>
        <div className="overflow-hidden rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>{['File','Owner','Type','Uploaded','Session'].map(h=> <th key={h} className="text-left px-3 py-2 font-medium text-gray-600">{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.id} className="border-t">
                  <td className="px-3 py-2">{f.filename}</td>
                  <td className="px-3 py-2 text-gray-500">{f.user_email}</td>
                  <td className="px-3 py-2">{f.filetype}</td>
                  <td className="px-3 py-2">{f.created_at ? new Date(f.created_at).toISOString().slice(0,10) : '-'}</td>
                  <td className="px-3 py-2 text-gray-500">{f.session_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {stats && Object.entries(stats).map(([k, v]) => (
          <div key={k} className="rounded-xl border p-3 text-sm bg-white"><div className="text-gray-500">{k}</div><div className="text-lg font-semibold">{v}</div></div>
        ))}
      </div>
    </div>
  );
}