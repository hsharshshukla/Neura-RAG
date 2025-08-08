import React from 'react';
import { useLocation } from 'react-router-dom';
import TopBar from './Topbar';

const Layout = ({ children }) => {
  const location = useLocation();
  const hideTopBar = ['/login', '/signup'].includes(location.pathname);

  return (
    <div className="min-h-screen flex flex-col">
      {!hideTopBar && <TopBar />}
      <main className="flex-grow">{children}</main>
    </div>
  );
};

export default Layout;
