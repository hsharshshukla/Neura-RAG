import { BrowserRouter as Router, Routes, Route, Navigate  } from 'react-router-dom';
import Chat from './pages/Chat';
import Profile from './pages/Profile';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Layout from './components/Layout';
import Settings from './pages/Settings';
// import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Home from './pages/Home'
import Pricing from './pages/Pricing'
import About from './pages/About'
import Privacy from './pages/Privacy'
import Terms from './pages/Terms'
import './themeBoot'; 

import ProtectedRoute from './components/ProtectedRoute';

function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/terms" element={<Terms />} />
          
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/" element={<Home />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/about" element={<About />} />
            {/* Back-compat: redirect old /home to / */}
          <Route path="/home" element={<Navigate to="/" replace />} />

          {/* Protected Routes */}
          <Route
            path="/chat/:id"
            element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
              // <Chat />
            }
          />
          <Route
            path="/chat"
            element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
              // <Chat />
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <Profile />
              </ProtectedRoute>
              // <Profile />
            }
          />
          <Route path="/about" element={<About />} />
          
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <Settings />
              </ProtectedRoute>
              // <Settings />
            }
          />
           {/* catch-all so unknown routes don't blank-screen */}
         <Route path="*" element={<div className="p-6">Page not found.</div>} />
       
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
