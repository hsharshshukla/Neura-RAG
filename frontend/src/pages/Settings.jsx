import React, { useState } from 'react';

const Settings = () => {
  const [name, setName] = useState('Tanya Sharma');
  const [email, setEmail] = useState(localStorage.getItem('email') || 'demo@user.com');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState('');

  const handleUpdateProfile = () => {
    setMessage('✅ Profile updated (dummy)');
    // TODO: Wire to backend
  };

  const handleChangePassword = () => {
    if (newPassword !== confirmPassword) {
      setMessage('❌ Passwords do not match');
      return;
    }
    setMessage('✅ Password changed (dummy)');
    // TODO: Wire to backend
  };

  const handleDeleteAccount = () => {
    const confirmed = window.confirm('Are you sure you want to delete your account? This cannot be undone.');
    if (confirmed) {
      setMessage('✅ Account deleted (dummy)');
      // TODO: Wire to backend
    }
  };

  const handleLogoutAll = () => {
    setMessage('✅ Logged out from all devices (dummy)');
    // TODO: Wire to backend
  };

  return (
    <div className="min-h-screen bg-gray-100 py-8 px-4 flex justify-center">
      <div className="bg-white rounded shadow-md p-6 w-full max-w-2xl space-y-8">
        <h2 className="text-2xl font-bold text-center">Account Settings</h2>

        {message && (
          <div className="bg-green-100 text-green-700 px-4 py-2 rounded">
            {message}
          </div>
        )}

        {/* Update Name + Email */}
        <div>
          <h3 className="text-lg font-semibold mb-2">Update Profile</h3>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Full Name"
            className="w-full p-2 border rounded mb-3"
          />
          <input
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="Email"
            className="w-full p-2 border rounded mb-3"
          />
          <button
            onClick={handleUpdateProfile}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
          >
            Save Changes
          </button>
        </div>

        {/* Change Password */}
        <div>
          <h3 className="text-lg font-semibold mb-2">Change Password</h3>
          <input
            type="password"
            placeholder="New Password"
            value={newPassword}
            onChange={e => setNewPassword(e.target.value)}
            className="w-full p-2 border rounded mb-3"
          />
          <input
            type="password"
            placeholder="Confirm New Password"
            value={confirmPassword}
            onChange={e => setConfirmPassword(e.target.value)}
            className="w-full p-2 border rounded mb-3"
          />
          <button
            onClick={handleChangePassword}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
          >
            Update Password
          </button>
        </div>

        {/* Logout All Devices */}
        <div>
          <h3 className="text-lg font-semibold mb-2">Logout from All Devices</h3>
          <button
            onClick={handleLogoutAll}
            className="bg-yellow-500 text-white px-4 py-2 rounded hover:bg-yellow-600"
          >
            Logout Everywhere
          </button>
        </div>
        <br/>
        {/* Delete Account */}
        <div>
          <h3 className="text-lg font-semibold mb-2 text-red-600">Danger Zone</h3>
          <button
            onClick={handleDeleteAccount}
            className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700"
          >
            Delete My Account
          </button>
        </div>

        {/* Coming Soon (Disabled Features) */}
        <div className="border-t pt-6 text-gray-400">
          <h3 className="text-lg font-semibold mb-2">Coming Soon</h3>
          <ul className="space-y-2 text-sm">
            <li>🛠 Billing settings</li>
            <li>🌗 Dark mode</li>
            <li>🔔 Notification preferences</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default Settings;
