// pages/Settings.jsx
import React, { useEffect, useState } from 'react';
import secureAxios from '../utils/secureAxios';

export default function SettingsPage() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [tier, setTier] = useState('free');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  // load profile
  useEffect(() => {
    (async () => {
      try {
        const { data } = await secureAxios.get('/user/profile');
        if (data?.email) setEmail(data.email);
        if (data?.name != null) setName(data.name || '');
        if (data?.plan) setTier((data.plan || '').toLowerCase());
      } catch {}
    })();
  }, []);

  const changePassword = async () => {
    if (!newPassword || newPassword !== confirmPassword) {
      setMessage('❌ Passwords do not match'); return;
    }
    setBusy(true); setMessage('');
    try {
      await secureAxios.post('/auth/change-password', { newPassword });
      setMessage('✅ Password changed. You may need to sign in again on other devices.');
      setNewPassword(''); setConfirmPassword('');
    } catch {
      setMessage('❌ Failed to change password');
    } finally {
      setBusy(false);
    }
  };

  const logoutAll = async () => {
    if (!confirm('Log out from all devices?')) return;
    setBusy(true); setMessage('');
    try {
      await secureAxios.post('/auth/logout-all');
      setMessage('✅ Logged out from all devices');
      window.location.href = '/login';
    } catch {
      setMessage('❌ Failed to logout everywhere');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Account</h2>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Name</label>
            <input
              value={name || '—'}
              readOnly
              disabled
              className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-gray-600"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Email</label>
            <input
              value={email || '—'}
              readOnly
              disabled
              className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-gray-600"
            />
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Security</h2>
        <div className="grid sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm text-gray-600 mb-1">New Password</label>
            <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="w-full rounded-xl border border-gray-200 dark:border-gray-700 p-3" />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Confirm Password</label>
            <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="w-full rounded-xl border border-gray-200 dark:border-gray-700 p-3" />
          </div>
          <div className="flex items-end">
            <button onClick={changePassword} disabled={busy} className="w-full bg-gradient-to-r from-teal-500 to-indigo-500 text-white px-4 py-2 rounded-xl shadow disabled:opacity-60">
              {busy ? 'Working…' : 'Update Password'}
            </button>
          </div>
        </div>

        <div className="mt-4">
          <button onClick={logoutAll} disabled={busy} className="px-4 py-2 rounded-xl border border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
            {busy ? 'Working…' : 'Logout from all devices'}
          </button>
        </div>
      </div>

      {message && <div className="bg-green-100 text-green-700 px-4 py-2 rounded">{message}</div>}
    </div>
  );
}


// // pages/Settings.jsx
// import React, { useEffect, useState } from 'react';
// import secureAxios from '../utils/secureAxios';

// export default function SettingsPage() {
//   const [name, setName] = useState('');
//   const [email, setEmail] = useState(localStorage.getItem('email') || '');
//   const [tier, setTier] = useState(localStorage.getItem('tier') || 'free');
//   const [newPassword, setNewPassword] = useState('');
//   const [confirmPassword, setConfirmPassword] = useState('');
//   const [message, setMessage] = useState('');
//   const [busy, setBusy] = useState(false);

//   // load profile
//   useEffect(() => {
//     (async () => {
//       try {
//         const { data } = await secureAxios.get('/user/me');
//         if (data?.email) setEmail(data.email);
//         if (data?.name != null) { setName(data.name); localStorage.setItem('name', data.name || ''); }
//         if (data?.tier) setTier(data.tier);
//       } catch {}
//     })();
//   }, []);

//   const saveProfile = async () => {
//     const n = (name || '').trim();
//     if (!n) { setMessage('❌ Name cannot be empty'); return; }
//     setBusy(true); setMessage('');
//     try {
//       const { data } = await secureAxios.patch('/user/me', { name: n });
//       setName(data?.name || n);
//       localStorage.setItem('name', data?.name || n);
//       setMessage('✅ Profile updated');
//     } catch {
//       setMessage('❌ Failed to update profile');
//     } finally {
//       setBusy(false);
//     }
//   };

//   const changePassword = async () => {
//     if (!newPassword || newPassword !== confirmPassword) {
//       setMessage('❌ Passwords do not match'); return;
//     }
//     setBusy(true); setMessage('');
//     try {
//       await secureAxios.post('/auth/change-password', { newPassword });
//       setMessage('✅ Password changed. You may need to sign in again on other devices.');
//       setNewPassword(''); setConfirmPassword('');
//     } catch {
//       setMessage('❌ Failed to change password');
//     } finally {
//       setBusy(false);
//     }
//   };

//   const logoutAll = async () => {
//     if (!confirm('Log out from all devices?')) return;
//     setBusy(true); setMessage('');
//     try {
//       await secureAxios.post('/auth/logout-all');
//       localStorage.removeItem('token');
//       setMessage('✅ Logged out from all devices');
//       window.location.href = '/login';
//     } catch {
//       setMessage('❌ Failed to logout everywhere');
//     } finally {
//       setBusy(false);
//     }
//   };

//   return (
//     <div className="max-w-2xl mx-auto p-6 space-y-6">
//       <h1 className="text-2xl font-bold mb-6">Settings</h1>

//       <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
//         <h2 className="text-lg font-semibold mb-4">Account</h2>
//         <div className="grid sm:grid-cols-2 gap-4">
//           <div>
//             <label className="block text-sm text-gray-600 mb-1">Name</label>
//             <input
//               value={name || '—'}
//               readOnly
//               disabled
//               className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-gray-600"
//             />
//           </div>
//           <div>
//             <label className="block text-sm text-gray-600 mb-1">Email</label>
//             <input
//               value={email || '—'}
//               readOnly
//               disabled
//               className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-gray-600"
//             />
//           </div>
//           {/* <div>
//             <label className="block text-sm text-gray-600 mb-1">Name</label>
//             <input
//               value={name}
//               onChange={(e)=>setName(e.target.value)}
//               className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3"
//               placeholder="Your name"
//               maxLength={80}
//             />
//           </div>
//           <div>
//             <label className="block text-sm text-gray-600 mb-1">Email</label>
//             <input
//               value={email}
//               disabled
//               className="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-gray-500"
//             />
//           </div> */}
//         </div>
        
//       </div>

//       <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
//         <h2 className="text-lg font-semibold mb-4">Security</h2>
//         <div className="grid sm:grid-cols-3 gap-4">
//           <div>
//             <label className="block text-sm text-gray-600 mb-1">New Password</label>
//             <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="w-full rounded-xl border border-gray-200 dark:border-gray-700 p-3" />
//           </div>
//           <div>
//             <label className="block text-sm text-gray-600 mb-1">Confirm Password</label>
//             <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="w-full rounded-xl border border-gray-200 dark:border-gray-700 p-3" />
//           </div>
//           <div className="flex items-end">
//             <button onClick={changePassword} disabled={busy} className="w-full bg-gradient-to-r from-teal-500 to-indigo-500 text-white px-4 py-2 rounded-xl shadow disabled:opacity-60">
//               {busy ? 'Working…' : 'Update Password'}
//             </button>
//           </div>
//         </div>

//         <div className="mt-4">
//           <button onClick={logoutAll} disabled={busy} className="px-4 py-2 rounded-xl border border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
//             {busy ? 'Working…' : 'Logout from all devices'}
//           </button>
//         </div>
//       </div>

//       {message && <div className="bg-green-100 text-green-700 px-4 py-2 rounded">{message}</div>}
//     </div>
//   );
// }


