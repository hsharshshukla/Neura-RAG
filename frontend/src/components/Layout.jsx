// src/components/Layout.jsx
import React from "react";
import { useLocation } from "react-router-dom";
import TopBar from "./TopBar";      // 👈 your file is TopBar.jsx (case matches)
/// import Footer from "./Footer";   // optional

export default function Layout({ children }) {
  const location = useLocation();

  // If you ever want to hide the header on some routes, use this:
  // const hideTopBar = false; // e.g., [''].includes(location.pathname)
  const hideTopBar = false; // ✅ show TopBar on EVERY page, including /login and /signup

  return (
    <div className="min-h-screen flex flex-col">
      {!hideTopBar && <TopBar />}
      <div className="flex-1">
        {children}
      </div>
      {/* <Footer /> */}
    </div>
  );
}


// import React from 'react';
// import { useLocation } from 'react-router-dom';
// import TopBar from './TopBar';
// import ConsentBanner from './ConsentBanner'; 

// const Layout = ({ children }) => {
//   const location = useLocation();
//   const hideTopBar = ['/login', '/signup'].includes(location.pathname);

//   return (
//     <div className="min-h-screen flex flex-col">
//       {!hideTopBar && <TopBar />}
//       {!hideTopBar && <ConsentBanner />}{/* ✅ show banner only when logged in pages */}
//       <main className="flex-grow">{children}</main>
//     </div>
//   );
// };

// export default Layout;
