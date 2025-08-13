// src/pages/Privacy.jsx
import React from "react";

export default function Privacy() {
  return (
    <div className="max-w-3xl mx-auto p-6 prose">
      <h1>Privacy Policy — Neura</h1>
      <p><strong>Effective:</strong> August 12, 2025 &nbsp; | &nbsp; <strong>Version:</strong> 1.1</p>

      <h2>1. Information We Collect</h2>
      <ul>
        <li><strong>Account</strong>: name, email, subscription status</li>
        <li><strong>Uploaded Data</strong>: files and messages you provide</li>
        <li><strong>Usage</strong>: chat logs, metadata, analytics</li>
        <li><strong>Payments</strong>: processed by Lemon Squeezy (we do not store card details)</li>
      </ul>

      <h2>2. How We Use Data</h2>
      <ul>
        <li>Operate and provide the Service</li>
        <li>Train, improve, and develop AI models (ours or third-party)</li>
        <li>Analytics and research (aggregated/anonymized)</li>
        <li>Prevent abuse and enforce Terms</li>
        <li>Comply with legal obligations</li>
      </ul>
      <p>By using Neura, you explicitly consent to your data being used for AI training and service improvement.</p>

      <h2>3. Sharing</h2>
      <ul>
        <li>Third-party AI providers (e.g., OpenAI) to process prompts/content</li>
        <li>Payment processors</li>
        <li>Hosting/infrastructure vendors</li>
        <li>Authorities when legally required</li>
      </ul>

      <h2>4. Retention</h2>
      <p>We retain data as needed for operations and improvement. Aggregated/anonymized data may be kept indefinitely.</p>

      <h2>5. Security</h2>
      <p>Encryption in transit and standard safeguards are used, but no system is 100% secure.</p>

      <h2>6. International Transfers</h2>
      <p>Your data may be processed in other countries. Using the Service implies consent to such transfers.</p>

      <h2>7. Your Rights</h2>
      <ul>
        <li>Access, correct, or delete your personal data</li>
        <li>Request export of your data</li>
      </ul>

      <h2>8. Children</h2>
      <p>We do not knowingly collect data from children under 13 without parental consent.</p>

      <h2>9. Changes</h2>
      <p>We may update this Policy. Continued use after updates constitutes acceptance.</p>

      <h2>Contact</h2>
      <p>privacy@neura.com</p>

      <footer className="text-sm text-gray-500 mt-8">
        Privacy Version: <strong>2025-08-01</strong>
      </footer>
    </div>
  );
}
