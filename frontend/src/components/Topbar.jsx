import React, { useState } from 'react';

const TopBar = () => {
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const handleLogout = () => {
    localStorage.clear();
    window.location.href = '/login';
  };

  return (
    <div className="w-full flex justify-between items-center bg-gray-800 text-white px-6 py-3 shadow-md relative">
      {/* Left: Neura logo/title */}
      <div
        className="text-xl font-semibold tracking-wide cursor-pointer"
        onClick={() => window.location.href = '/chat'}
      >
        🧠 Neura
      </div>

      {/* Right: Profile dropdown */}
      <div className="relative">
        <button
          onClick={() => setDropdownOpen(!dropdownOpen)}
          className="font-medium hover:underline"
        >
          Profile ▼
        </button>

        {dropdownOpen && (
          <div className="absolute top-full right-0 mt-2 bg-white text-black rounded shadow-lg z-50 w-40">
            <button
              onClick={() => window.location.href = '/profile'}
              className="block w-full text-left px-4 py-2 hover:bg-gray-100"
            >
              👤 View Profile
            </button>
            <button
              onClick={handleLogout}
              className="block w-full text-left px-4 py-2 hover:bg-gray-100"
            >
              🚪 Logout
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default TopBar;
