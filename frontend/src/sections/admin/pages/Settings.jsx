// ============================
// File: src/sections/admin/pages/Settings.jsx
// ============================
import { useEffect, useState } from 'react';
import secureAxios from '../../../utils/secureAxios';
import Card from '../components/Card';

export default function Settings() {
  const [cfg, setCfg] = useState({ openai_key_masked: '********', vector_path: './vector_store', ocr: 'Tesseract' });
  useEffect(() => {
    (async () => {
      try { const { data } = await secureAxios.get('/admin/settings'); setCfg(data); } catch {}
    })();
  }, []);

  return (
    <Card title="System Settings" action={<button className="text-sm px-3 py-1.5 rounded-lg border">Edit</button>}>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
        <div className="rounded-xl border p-3 bg-white"><div className="text-gray-500">OpenAI Key</div><div className="truncate">{cfg.openai_key_masked}</div></div>
        <div className="rounded-xl border p-3 bg-white"><div className="text-gray-500">Vector Store Path</div><div>{cfg.vector_path}</div></div>
        <div className="rounded-xl border p-3 bg-white"><div className="text-gray-500">OCR Engine</div><div>{cfg.ocr}</div></div>
      </div>
    </Card>
  );
}