// ============================
// File: src/sections/admin/pages/Billing.jsx
// ============================
import { useEffect, useState } from 'react';
import secureAxios from '../../../utils/secureAxios';
import Card from '../components/Card';

export default function Billing() {
  const [stats, setStats] = useState(null);
  const [webhooks, setWebhooks] = useState([]);
  useEffect(() => {
    (async () => {
      try {
        const s = await secureAxios.get('/admin/billing/stats');
        const w = await secureAxios.get('/admin/billing/webhooks');
        setStats(s.data);
        setWebhooks(w.data.items || []);
      } catch {
        setStats(null); setWebhooks([]);
      }
    })();
  }, []);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {stats && Object.entries(stats).map(([k, v]) => (
          <div key={k} className="rounded-xl border p-3 text-sm bg-white"><div className="text-gray-500">{k}</div><div className="text-lg font-semibold">{v}</div></div>
        ))}
      </div>
      <Card title="Webhook Log">
        <div className="overflow-auto rounded-xl border">
          <table className="w-full text-sm">
            <thead className="bg-gray-50"><tr><th className="px-3 py-2 text-left">Event</th><th className="px-3 py-2 text-left">Status</th><th className="px-3 py-2 text-left">Received</th></tr></thead>
            <tbody>
              {webhooks.map((e) => (
                <tr key={e.id} className="border-t"><td className="px-3 py-2">{e.event}</td><td className="px-3 py-2">{e.status}</td><td className="px-3 py-2">{new Date(e.created_at).toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
