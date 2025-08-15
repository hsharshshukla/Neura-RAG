// ============================
// File: src/sections/admin/pages/Overview.jsx
// ============================
import { useEffect, useState } from 'react';
import secureAxios from '../../../utils/secureAxios';
import Kpi from '../components/Kpi';
import Card from '../components/Card';

export default function Overview() {
  const [metrics, setMetrics] = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const { data } = await secureAxios.get('/admin/metrics');
        setMetrics(data);
      } catch {
        setMetrics({ active_users_24h: 0, uploads_24h: 0, queries_24h: 0, free_to_pro: 0 });
      }
    })();
  }, []);
  const m = metrics || { active_users_24h: 0, uploads_24h: 0, queries_24h: 0, free_to_pro: 0 };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi label="Active Users (24h)" value={m.active_users_24h} />
        <Kpi label="Uploads (24h)" value={m.uploads_24h} />
        <Kpi label="Queries (24h)" value={m.queries_24h} />
        <Kpi label="Free → Pro" value={`${m.free_to_pro}%`} />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <Card title="Queries over time"><div className="h-72 rounded-xl border border-dashed" /></Card>
        <Card title="User Tier Distribution"><div className="h-72 rounded-xl border border-dashed" /></Card>
      </div>
    </div>
  );
}
