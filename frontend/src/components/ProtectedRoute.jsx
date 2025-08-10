import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const ProtectedRoute = ({ children }) => {
  const [checking, setChecking] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    // const email = localStorage.getItem('email');
    // if (!email) {
    const token  = localStorage.getItem('token');
    if(!token){
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
