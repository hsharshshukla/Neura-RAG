// src/components/AdminRoute.jsx
import { Navigate, useLocation } from 'react-router-dom';
import { getToken, getRole } from '../utils/auth';

export default function AdminRoute({ children }) {
  const location = useLocation();
  const token = getToken();
  const role = getRole();

  if (!token || role !== 'admin') {
    // ⬅️ carry where the user tried to go
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}

