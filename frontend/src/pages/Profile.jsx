// src/pages/profile.jsx
import React, { useEffect, useState } from 'react';
import secureAxios from '../utils/secureAxios';

const Profile = () => {
  const [profile, setProfile] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const loadProfile = async () => {
    setError('');
    try {
      const res = await secureAxios.get('/user/profile', {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      });
      setProfile(res.data);
    } catch (err) {
      console.error('Failed to fetch profile:', err);
      setError('Failed to load profile. Please refresh.');
    }
  };

  useEffect(() => {
    loadProfile();
  }, []);

  const handleSave = async () => {
    if (!profile?.name?.trim()) return;
    setSaving(true);
    setError('');
    try {
      await secureAxios.patch(
        '/user/profile',
        { name: profile.name.trim() },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      // reflect immediately for navbar etc.
      localStorage.setItem('name', profile.name.trim());
    } catch (err) {
      console.error('Failed to save profile:', err);
      setError('Could not save changes. Try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = () => {
    localStorage.clear();
    window.location.href = '/login';
  };

  if (!profile && !error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-500">Loading profile…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-2xl mx-auto space-y-4">
        {/* Error banner */}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3">
            {error}
          </div>
        )}

        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold mb-6">My Profile</h2>

          {/* Header: Avatar + Plan */}
          <div className="flex items-center gap-4">
            <img
              src={`https://ui-avatars.com/api/?name=${encodeURIComponent(
                profile?.name || 'User'
              )}`}
              alt="avatar"
              className="h-16 w-16 rounded-full"
            />
            <div>
              <div className="text-sm text-gray-500">Plan</div>
              <div className="inline-flex items-center px-2 py-1 rounded-lg border border-gray-200 text-sm">
                {profile?.plan || 'Free'}
              </div>
            </div>
          </div>

          {/* Fields */}
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
              <label className="block text-sm text-gray-600 mb-1">Email </label>
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

          {/* Actions */}
          <div className="mt-6 flex flex-wrap gap-2">
            <button
              onClick={handleLogout}
              className="px-4 py-2 rounded-xl border border-gray-200"
            >
              Logout
            </button>
          </div>


        </div>
      </div>
    </div>
  );
};

export default Profile;


