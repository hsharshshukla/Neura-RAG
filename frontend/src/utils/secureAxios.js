import axios from 'axios';

const secureAxios = () => {
  const token = localStorage.getItem('token');

  return axios.create({
    baseURL: 'http://localhost:8000/api/v1',
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
};

export default secureAxios;
