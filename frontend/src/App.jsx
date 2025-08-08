import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Chat from './pages/Chat';
import Profile from './pages/Profile';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Layout from './components/Layout';
import Settings from './pages/Settings';

import ProtectedRoute from './components/ProtectedRoute';

function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          {/* Protected Routes */}
          <Route
            path="/chat"
            element={
              // <ProtectedRoute>
              //   <Chat />
              // </ProtectedRoute>
              <Chat />
            }
          />
          <Route
            path="/profile"
            element={
              // <ProtectedRoute>
              //   <Profile />
              // </ProtectedRoute>
              <Profile />
            }
          />
          
          <Route
            path="/settings"
            element={
              // <ProtectedRoute>
              //   <Settings />
              // </ProtectedRoute>
              <Settings />
            }
          />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
