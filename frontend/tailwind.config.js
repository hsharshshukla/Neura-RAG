/** @type {import('tailwindcss').Config} */
// tailwind.config.js
module.exports = {
  darkMode: 'class',                     // ✅ required for toggling via .dark
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: { extend: {} },
  plugins: [
    require('@tailwindcss/typography'),  // optional but you’re using prose
  ],
};

// module.exports = {
//   content: [
//     "./src/**/*.{js,jsx,ts,tsx}"
//   ],
  
//   theme: {
//     extend: {},
//   },
//   plugins: [],
// }
