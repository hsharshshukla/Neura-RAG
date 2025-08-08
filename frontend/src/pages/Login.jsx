import React, { useState } from 'react';
import axios from 'axios';
import secureAxios from '../utils/secureAxios';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const login = async () => {
    try {
      const res = await secureAxios.post(
        //'http://localhost:8000/api/v1/login',
        '/login',
        new URLSearchParams({
          email,
          password,
        })
      );
  
      if (res.data?.email) {
        localStorage.setItem('email', res.data.email);        
        localStorage.setItem('tier', res.data.tier); // optional for pro/free logic
        localStorage.setItem('token', res.data.access_token);
        window.location.href = '/chat';
      } else {
        setError('Invalid login response');
      }
    } catch (err) {
      console.error("Login failed", err);
      setError('Invalid email or password');
    }
  };
  
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white shadow-lg rounded px-8 py-6 w-full max-w-md">
        <h2 className="text-2xl font-semibold mb-4 text-center">Login to Neura</h2>

        {error && (
          <div className="bg-red-100 text-red-700 px-4 py-2 rounded mb-4">
            {error}
          </div>
        )}

        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="Email"
          className="w-full p-2 mb-4 border rounded"
        />
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Password"
          className="w-full p-2 mb-4 border rounded"
        />

        <button
          onClick={login}
          className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700"
        >
          Login
        </button>

        {/* Register Link */}
        <div className="text-center mt-4">
          <span className="text-sm text-gray-600">
            Don’t have an account?{' '}
            <a href="/signup" className="text-blue-600 hover:underline">
              Register
            </a>
          </span>
        </div>
      </div>
    </div>
  );
};

export default Login;
