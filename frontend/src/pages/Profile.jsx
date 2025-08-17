// src/pages/profile.jsx
import React, { useEffect, useState } from 'react';
import secureAxios from '../utils/secureAxios';

const TierPill = ({ tier }) => {
  const t = (tier || 'free').toLowerCase();
  return (
    <span
      title="Your current plan"
      className="inline-flex items-center px-2 py-1 rounded-lg border border-gray-200 text-xs font-medium bg-gray-100 text-gray-800"
    >
      {t.toUpperCase()}
    </span>
  );
};

const Profile = () => {
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState('');

  const normalizeProfile = (raw) => {
    if (!raw) return null;
    const p = raw.user || raw;
    const tier = (p.tier || p.plan || 'free').toLowerCase();
    const created =
      p.joinDate || p.created_at || p.createdAt || null;
    return {
      name: p.name || 'User',
      email: p.email || '',
      tier,
      joinDate: created ? new Date(created).toLocaleString() : '',
    };
  };

  const loadProfile = async () => {
    setError('');
    try {
      // Only call the endpoints you actually have to avoid 404 noise.
      const res =
        (await secureAxios.get('/auth/me').catch(() => null)) ||
        (await secureAxios.get('/user/profile').catch(() => null));
      if (!res?.data) throw new Error('No profile data');
      setProfile(normalizeProfile(res.data));
    } catch (err) {
      console.error('Failed to fetch profile:', err);
      setError('Failed to load profile. Please refresh.');
    }
  };

  useEffect(() => {
    loadProfile();
  }, []);

  const handleLogout = async () => {
    try { await secureAxios.post('/auth/logout'); } catch {}
    window.location.href = '/login';
  };

  if (!profile && !error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-500">Loading profile…</div>
      </div>
    );
  }

  const isFree = (profile?.tier || 'free').toLowerCase() === 'free';

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-2xl mx-auto space-y-4">
        {error && (
          <div className="rounded-2xl border border-red-200 bg-red-50 text-red-700 px-4 py-3">
            {error}
          </div>
        )}

        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold mb-6">My Profile</h2>

          <div className="flex items-center gap-4">
            <img
              src={`https://ui-avatars.com/api/?name=${encodeURIComponent(
                profile?.name || 'User'
              )}`}
              alt="avatar"
              className="h-16 w-16 rounded-full"
            />
            <div className="space-y-1">
              <div className="text-sm text-gray-500">Plan</div>
              <div className="flex items-center gap-2">
                <TierPill tier={profile?.tier} />
                {/* No scope badge on profile page */}
              </div>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-4 mt-6">
            <div>
              <label className="block text-sm text-gray-600 mb-1">Name</label>
              <input
                value={profile?.name || '—'}
                readOnly
                disabled
                className="w-full p-3 rounded-xl border border-gray-200 bg-gray-50 text-gray-600"
                placeholder="Full name"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-600 mb-1">Email</label>
              <input
                value={profile?.email || ''}
                disabled
                className="w-full p-3 rounded-xl border border-gray-200 bg-gray-50 text-gray-500"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-600 mb-1">Join Date</label>
              <input
                value={profile?.joinDate || ''}
                disabled
                className="w-full p-3 rounded-xl border border-gray-200 bg-gray-50 text-gray-500"
              />
            </div>
          </div>

          <div className="mt-6 flex flex-wrap gap-2">
            <button
              onClick={handleLogout}
              className="px-4 py-2 rounded-xl border border-gray-200 hover:bg-gray-50"
            >
              Logout
            </button>

            {isFree ? (
              <a
                href="/pricing"
                className="px-4 py-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700"
              >
                Upgrade to Mini+ / Pro
              </a>
            ) : (
              <a
                href="/billing"
                className="px-4 py-2 rounded-xl border border-gray-200 hover:bg-gray-50"
              >
                Manage billing
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Profile;


// // src/pages/profile.jsx
// import React, { useEffect, useState } from 'react';
// import secureAxios from '../utils/secureAxios';
// import ScopeBadge from '../components/ScopeBadge';

// const TierPill = ({ tier }) => {
//   const t = (tier || 'free').toLowerCase();
//   return (
//     <span
//       title="Your current plan"
//       className="inline-flex items-center px-2 py-1 rounded-lg border border-gray-200 text-xs font-medium bg-gray-100 text-gray-800"
//     >
//       {t.toUpperCase()}
//     </span>
//   );
// };

// const Profile = () => {
//   const [profile, setProfile] = useState(null);
//   const [error, setError] = useState('');

//   const normalizeProfile = (raw) => {
//     if (!raw) return null;
//     // Accept multiple backend shapes:
//     // - { email, name, tier, created_at }
//     // - { email, name, plan, joinDate }
//     // - { user: {...} }
//     const p = raw.user || raw;
//     const tier = (p.tier || p.plan || 'free').toLowerCase();
//     return {
//       name: p.name || 'User',
//       email: p.email || '',
//       tier,
//       joinDate:
//         p.joinDate ||
//         p.created_at ||
//         p.createdAt ||
//         (p.created_at ? new Date(p.created_at).toLocaleString() : ''),
//     };
//   };

//   const loadProfile = async () => {
//     setError('');
//     try {
//       // Try common endpoints in order
//       const res =
//         (await secureAxios.get('/me').catch(() => null)) ||
//         (await secureAxios.get('/auth/me').catch(() => null)) ||
//         (await secureAxios.get('/user/profile').catch(() => null));
//       if (!res?.data) throw new Error('No profile data');
//       setProfile(normalizeProfile(res.data));
//     } catch (err) {
//       console.error('Failed to fetch profile:', err);
//       setError('Failed to load profile. Please refresh.');
//     }
//   };

//   useEffect(() => {
//     loadProfile();
//   }, []);

//   const handleLogout = async () => {
//     try { await secureAxios.post('/auth/logout'); } catch {}
//     window.location.href = '/login';
//   };

//   if (!profile && !error) {
//     return (
//       <div className="min-h-screen flex items-center justify-center bg-gray-50">
//         <div className="text-gray-500">Loading profile…</div>
//       </div>
//     );
//   }

//   const isFree = (profile?.tier || 'free').toLowerCase() === 'free';

//   return (
//     <div className="min-h-screen bg-gray-50 py-8 px-4">
//       <div className="max-w-2xl mx-auto space-y-4">
//         {error && (
//           <div className="rounded-2xl border border-red-200 bg-red-50 text-red-700 px-4 py-3">
//             {error}
//           </div>
//         )}

//         <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
//           <h2 className="text-xl font-semibold mb-6">My Profile</h2>

//           <div className="flex items-center gap-4">
//             <img
//               src={`https://ui-avatars.com/api/?name=${encodeURIComponent(
//                 profile?.name || 'User'
//               )}`}
//               alt="avatar"
//               className="h-16 w-16 rounded-full"
//             />
//             <div className="space-y-1">
//               <div className="text-sm text-gray-500">Plan</div>
//               <div className="flex items-center gap-2">
//                 <TierPill tier={profile?.tier} />
//                 {/* <ScopeBadge tier={(profile?.tier || 'free').toLowerCase()} /> */}
//               </div>
//             </div>
//           </div>

//           <div className="grid sm:grid-cols-2 gap-4 mt-6">
//             <div>
//               <label className="block text-sm text-gray-600 mb-1">Name</label>
//               <input
//                 value={profile?.name || '—'}
//                 readOnly
//                 disabled
//                 className="w-full p-3 rounded-xl border border-gray-200 bg-gray-50 text-gray-600"
//                 placeholder="Full name"
//               />
//             </div>

//             <div>
//               <label className="block text-sm text-gray-600 mb-1">Email</label>
//               <input
//                 value={profile?.email || ''}
//                 disabled
//                 className="w-full p-3 rounded-xl border border-gray-200 bg-gray-50 text-gray-500"
//               />
//             </div>

//             <div>
//               <label className="block text-sm text-gray-600 mb-1">Join Date</label>
//               <input
//                 value={profile?.joinDate || ''}
//                 disabled
//                 className="w-full p-3 rounded-xl border border-gray-200 bg-gray-50 text-gray-500"
//               />
//             </div>
//           </div>

//           <div className="mt-6 flex flex-wrap gap-2">
//             <button
//               onClick={handleLogout}
//               className="px-4 py-2 rounded-xl border border-gray-200 hover:bg-gray-50"
//             >
//               Logout
//             </button>

//             {isFree ? (
//               <a
//                 href="/pricing"
//                 className="px-4 py-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700"
//               >
//                 Upgrade to Mini+ / Pro
//               </a>
//             ) : (
//               <a
//                 href="/billing"
//                 className="px-4 py-2 rounded-xl border border-gray-200 hover:bg-gray-50"
//               >
//                 Manage billing
//               </a>
//             )}
//           </div>
//         </div>
//       </div>
//     </div>
//   );
// };

// export default Profile;
