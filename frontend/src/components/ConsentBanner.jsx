import { useState } from 'react';
import secureAxios from '../utils/secureAxios';

export default function ConsentBanner() {
  const [show, setShow] = useState(localStorage.getItem('needs_reconsent') === '1');

  if (!show) return null;

  const accept = async () => {
    try {
      await secureAxios.post('/auth/accept-terms');
      localStorage.removeItem('needs_reconsent');
      setShow(false);
    } catch {
      alert('Failed to record acceptance. Please try again.');
    }
  };

  return (
    <div className="w-full bg-amber-50 border-b border-amber-200 text-amber-900">
      <div className="max-w-5xl mx-auto px-4 py-2 flex items-center justify-between">
        <span className="text-sm">
          Our Terms & Privacy have changed. Please review and accept to continue.
        </span>
        <div className="flex gap-2">
          <a href="/terms" target="_blank" className="text-sm underline">Terms</a>
          <a href="/privacy" target="_blank" className="text-sm underline">Privacy</a>
          <button onClick={accept} className="text-sm px-3 py-1 rounded bg-zinc-900 text-white">Accept</button>
        </div>
      </div>
    </div>
  );
}
