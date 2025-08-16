// src/components/ProtectedRoute.jsx
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { isLoggedIn } from '../utils/auth';

const ProtectedRoute = ({ children }) => {
  const [checking, setChecking] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    if (!isLoggedIn()) {
      navigate('/login');
    } else {
      setChecking(false);
    }
  }, [navigate]);

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="text-gray-500 animate-pulse text-lg">Checking authentication...</div>
      </div>
    );
  }

  return <>{children}</>;
};

export default ProtectedRoute;
