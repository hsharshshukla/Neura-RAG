export default function Pricing() {
  const tiers = [
    {
      name: 'Free',
      price: '₹0',
      features: [
        '20 chats/day',
        'Session-only search',
        'Basic OCR',
        'Upload documents (txt, pdf, docx, pptx, xlsx, images)',
        'Reference by document name',
      ],
      cta: 'Get started',
      primary: false,
    },
    {
      name: 'Mini+',
      price: '₹149/mo',
      features: [
        'Unlimited chats',
        'Session-only search',
        'Faster responses',
        'Upload documents (same as Free)',
        'Reference by document name',
      ],
      cta: 'Choose Mini+',
      primary: true, // highlight this as the recommended plan
    },
    {
      name: 'Pro',
      price: '₹500/mo',
      features: [
        'Unlimited chats',
        'Global document search',
        'Priority queue (faster responses)',
        'Premium support',
        'Upload documents (same as Free)',
        'Reference by document name',
      ],
      cta: 'Upgrade to Pro',
      primary: false,
    },
    {
      name: 'Enterprise',
      price: 'Custom',
      features: [
        'Unlimited chats',
        'Multi-seat',
        'Bulk ingestion & API',
        'SLA & SSO',
        'Dedicated support',
      ],
      cta: 'Contact sales',
      primary: false,
    },
  ];

  return (
    <section className="py-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <h1 className="text-3xl font-semibold text-gray-900">Pricing</h1>
        <p className="mt-2 text-gray-700">Simple plans that scale with your needs.</p>

        <div className="mt-8 grid lg:grid-cols-4 md:grid-cols-2 gap-6">
          {tiers.map((t) => (
            <div
              key={t.name}
              className={`rounded-2xl border ${
                t.primary ? 'border-indigo-600 shadow-md' : 'border-gray-200'
              } bg-white p-6`}
            >
              <div
                className={`text-sm font-medium ${
                  t.primary ? 'text-indigo-600' : 'text-gray-600'
                }`}
              >
                {t.name}
              </div>
              <div className="mt-1 text-3xl font-semibold">{t.price}</div>
              <ul className="mt-4 space-y-2 text-sm text-gray-700">
                {t.features.map((f) => (
                  <li key={f} className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-gray-400"></span>
                    {f}
                  </li>
                ))}
              </ul>
              <button
                className={`mt-6 w-full rounded-xl px-4 py-2.5 text-sm font-medium ${
                  t.primary
                    ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                    : 'bg-gray-900 text-white hover:bg-black'
                }`}
              >
                {t.cta}
              </button>
            </div>
          ))}
        </div>

        <div className="mt-10 text-sm text-gray-600">
          <h3 className="font-medium text-gray-900">FAQs</h3>
          <p className="mt-2">
            • All plans can upload documents and reference them by name. Export is currently not
            available.
          </p>
          <p className="mt-2">
            • Free and Mini+ use session-only search. Pro unlocks global document search across all
            your uploads and sessions.
          </p>
          <p className="mt-2">
            • Chat limits: Free = 20 chats/day; Mini+/Pro/Enterprise = unlimited (with priority
            queuing for faster responses on paid plans).
          </p>
          <p className="mt-2">
            • Billing is handled via our payment provider. You can cancel anytime.
          </p>
        </div>
      </div>
    </section>
  );
}
