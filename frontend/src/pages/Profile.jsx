import React, { useEffect, useState } from 'react';
import secureAxios from '../utils/secureAxios';

const Profile = () => {
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const res = await secureAxios().get('/user/profile');
        setProfile(res.data);
      } catch (err) {
        console.error('Failed to fetch profile:', err);
      }
    };

    fetchProfile();
  }, []);

  const handleLogout = () => {
    localStorage.clear();
    window.location.href = '/login';
  };

  if (!profile) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <p className="text-gray-500">Loading profile...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <div className="bg-white shadow-lg rounded px-8 py-6 w-full max-w-md">
        <h2 className="text-2xl font-semibold mb-6 text-center">My Profile</h2>

        <div className="space-y-4 text-sm text-gray-700">
          <div>
            <p className="text-gray-500">Name</p>
            <p className="text-lg font-medium">{profile.name}</p>
          </div>

          <div>
            <p className="text-gray-500">Email</p>
            <p className="text-lg font-medium">{profile.email}</p>
          </div>

          <div>
            <p className="text-gray-500">User ID</p>
            <p className="text-lg font-mono text-blue-600">{profile.userId}</p>
          </div>

          <div>
            <p className="text-gray-500">Plan</p>
            <p className="text-lg font-medium text-blue-700">{profile.plan}</p>
          </div>

          <div>
            <p className="text-gray-500">Join Date</p>
            <p className="text-lg font-medium">{profile.joinDate}</p>
          </div>

          <div>
            <p className="text-gray-500">Files Uploaded</p>
            <p className="text-lg font-medium">{profile.filesUploaded}</p>
          </div>

          <div>
            <p className="text-gray-500">Chats Created</p>
            <p className="text-lg font-medium">{profile.chatsCreated}</p>
          </div>
        </div>

        <button
          onClick={handleLogout}
          className="w-full bg-red-600 text-white py-2 mt-6 rounded hover:bg-red-700"
        >
          Logout
        </button>
      </div>
    </div>
  );
};

export default Profile;
