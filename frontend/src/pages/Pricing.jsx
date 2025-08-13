export default function Pricing(){
    const tiers = [
      {name:'Free', price:'₹0', features:['20 chats/day','Session-only search','Basic OCR'], cta:'Get started', primary:false},
      {name:'Mini+', price:'₹149/mo', features:['Unlimited chats','Faster responses','Priority queue'], cta:'Choose Mini+', primary:true},
      {name:'Pro', price:'₹500/mo', features:['Global doc search','Chat export (.md/.txt)','Premium support'], cta:'Upgrade to Pro', primary:false},
      {name:'Enterprise', price:'Custom', features:['Multi-seat','Bulk ingestion & API','SLA & SSO'], cta:'Contact sales', primary:false},
    ]
  
    return (
      <section className="py-16">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-semibold text-gray-900">Pricing</h1>
          <p className="mt-2 text-gray-700">Simple plans that scale with your team.</p>
          <div className="mt-8 grid lg:grid-cols-4 md:grid-cols-2 gap-6">
            {tiers.map((t) => (
              <div key={t.name} className={`rounded-2xl border ${t.primary ? 'border-indigo-600 shadow-md' : 'border-gray-200'} bg-white p-6`}>
                <div className={`text-sm font-medium ${t.primary ? 'text-indigo-600' : 'text-gray-600'}`}>{t.name}</div>
                <div className="mt-1 text-3xl font-semibold">{t.price}</div>
                <ul className="mt-4 space-y-2 text-sm text-gray-700">
                  {t.features.map((f)=> (<li key={f} className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-gray-400"></span>{f}</li>))}
                </ul>
                <button className={`mt-6 w-full rounded-xl px-4 py-2.5 text-sm font-medium ${t.primary ? 'bg-indigo-600 text-white hover:bg-indigo-700' : 'bg-gray-900 text-white hover:bg-black'}`}>{t.cta}</button>
              </div>
            ))}
          </div>
          <div className="mt-10 text-sm text-gray-600">
            <h3 className="font-medium text-gray-900">FAQs</h3>
            <p className="mt-2">• Free plan is session-scoped for search. Pro unlocks global document search across all uploads.</p>
            <p className="mt-2">• Payments are handled via Lemon Squeezy. You can cancel anytime.</p>
          </div>
        </div>
      </section>
    )
  }
  