import React, { useState } from 'react';
import secureAxios from '../utils/secureAxios'; // or use 'axios' if you prefer

const Signup = () => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const register = async () => {
    setError('');
    setSuccess('');

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    try {
      const params = new URLSearchParams();
      params.append('email', email);
      params.append('password', password);
      if (name) params.append('name', name);

      const res = await secureAxios.post('/auth/signup', params, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded'
        }
      });


      

      localStorage.setItem('email', res.data.email);
      localStorage.setItem('tier', res.data.tier);
      localStorage.setItem('token', res.data.access_token);

      setSuccess("Registration successful! Redirecting to chat...");
      setTimeout(() => {
        window.location.href = '/chat';
      }, 1500);
    } catch (err) {
      const data = err?.response?.data;

      let message = "Login failed";
      if (typeof data === "string") {
        message = data;
      } else if (data?.detail) {
        if (Array.isArray(data.detail)) {
          // Pydantic validation errors -> join all messages
          message = data.detail.map(e => e.msg || JSON.stringify(e)).join(", ");
        } else if (typeof data.detail === "string") {
          message = data.detail;
        }
      } else if (err?.message) {
        message = err.message;
      }
    
      console.error("Login failed:", data || err);
      setError(message); 

    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white shadow-lg rounded px-8 py-6 w-full max-w-md">
        <h2 className="text-2xl font-semibold mb-4 text-center">Create Your Neura Account</h2>

        {error && (
          <div className="bg-red-100 text-red-700 px-4 py-2 rounded mb-4">
            {error}
          </div>
        )}
        {success && (
          <div className="bg-green-100 text-green-700 px-4 py-2 rounded mb-4">
            {success}
          </div>
        )}

        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Full Name (optional)"
          className="w-full p-2 mb-4 border rounded"
        />

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

        <input
          type="password"
          value={confirmPassword}
          onChange={e => setConfirmPassword(e.target.value)}
          placeholder="Confirm Password"
          className="w-full p-2 mb-4 border rounded"
        />

        <button
          onClick={register}
          className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700"
        >
          Register
        </button>

        <div className="text-center mt-4">
          <span className="text-sm text-gray-600">
            Already have an account?{' '}
            <a href="/login" className="text-blue-600 hover:underline">
              Login
            </a>
          </span>
        </div>
      </div>
    </div>
  );
};

export default Signup;
