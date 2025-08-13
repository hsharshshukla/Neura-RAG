import { Link } from 'react-router-dom'

function CheckIcon(props){
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={props.className || 'h-5 w-5'}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}

export default function Home(){
  return (
    <>
      {/* Hero */}
      <section className="bg-gradient-to-b from-white to-indigo-50/60">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20 grid md:grid-cols-2 gap-10 items-center">
          <div>
            <h1 className="text-4xl sm:text-5xl font-semibold leading-tight text-gray-900">Neura — AI copilot for <span className="text-indigo-600">ECM consultants</span></h1>
            <p className="mt-4 text-lg text-gray-700">Upload documents, ask questions, and get instant answers with OCR + vector search. Built for OpenText, content-heavy projects, and rapid delivery.</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/signup" className="inline-flex items-center rounded-xl bg-indigo-600 px-4 py-2.5 text-white font-medium hover:bg-indigo-700">Start free</Link>
              <Link to="/pricing" className="inline-flex items-center rounded-xl border border-gray-300 px-4 py-2.5 text-gray-800 hover:border-gray-400">See plans</Link>
            </div>
            <div className="mt-6 flex flex-wrap gap-4 text-sm text-gray-600">
              <span className="inline-flex items-center gap-2"><CheckIcon/>OCR-enabled</span>
              <span className="inline-flex items-center gap-2"><CheckIcon/>Secure & private</span>
              <span className="inline-flex items-center gap-2"><CheckIcon/>Boost productivity</span>
            </div>
          </div>
          <div className="md:pl-8">
            <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
              {/* Placeholder app preview card */}
              <div className="aspect-video rounded-xl bg-gray-100 grid place-items-center text-gray-500">
                <div className="text-center">
                  <div className="font-semibold">Chat Preview</div>
                  <div className="text-sm">Your chats, sources, and uploads</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Purpose */}
      <section className="py-16">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <h2 className="text-2xl font-semibold text-gray-900">Why Neura</h2>
          <p className="mt-3 text-gray-700 max-w-3xl">Purpose-built for ECM (OpenText) consultants: cut research time, reduce manual document digging, and deliver faster with GPT-powered retrieval-augmented answers.</p>
          <div className="mt-8 grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {[
              {title:'OCR + Vector Search',desc:'Understand PDFs, images, and docs with chunked embeddings.'},
              {title:'Tiered Access',desc:'Free (session-only), Pro (global search), Enterprise (bulk ingest).'},
              {title:'Chat History',desc:'Resume any thread; export chats on Pro.'},
              {title:'Secure by Design',desc:'Scoped access, metadata filters, ownership retained.'},
            ].map((f,i)=> (
              <div key={i} className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                <div className="text-indigo-600 font-semibold">{f.title}</div>
                <p className="mt-2 text-sm text-gray-700">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Plans summary (teaser) */}
      <section className="py-16 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex items-end justify-between">
            <h2 className="text-2xl font-semibold text-gray-900">Plans</h2>
            <Link to="/pricing" className="text-sm text-indigo-600 hover:underline">Full pricing →</Link>
          </div>
          <div className="mt-8 grid md:grid-cols-3 gap-6">
            {/* Free */}
            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-6">
              <div className="text-sm font-medium text-gray-600">Free</div>
              <div className="mt-1 text-3xl font-semibold">₹0</div>
              <ul className="mt-4 space-y-2 text-sm text-gray-700">
                <li className="flex items-center gap-2"><CheckIcon/>20 chats/day</li>
                <li className="flex items-center gap-2"><CheckIcon/>Session-scoped search</li>
                <li className="flex items-center gap-2"><CheckIcon/>Basic OCR</li>
              </ul>
              <Link to="/signup" className="mt-6 inline-flex w-full items-center justify-center rounded-xl bg-gray-900 px-4 py-2.5 text-white hover:bg-black">Get started</Link>
            </div>
            {/* Mini+ */}
            <div className="rounded-2xl border-2 border-indigo-600 bg-white p-6 shadow-md">
              <div className="text-sm font-medium text-indigo-600">Mini+</div>
              <div className="mt-1 text-3xl font-semibold">₹149<span className="text-base font-normal text-gray-600">/mo</span></div>
              <ul className="mt-4 space-y-2 text-sm text-gray-700">
                <li className="flex items-center gap-2"><CheckIcon/>Unlimited chats</li>
                <li className="flex items-center gap-2"><CheckIcon/>Faster responses</li>
                <li className="flex items-center gap-2"><CheckIcon/>Priority queue</li>
              </ul>
              <Link to="/pricing" className="mt-6 inline-flex w-full items-center justify-center rounded-xl bg-indigo-600 px-4 py-2.5 text-white hover:bg-indigo-700">Compare plans</Link>
            </div>
            {/* Pro */}
            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-6">
              <div className="text-sm font-medium text-gray-600">Pro</div>
              <div className="mt-1 text-3xl font-semibold">₹500<span className="text-base font-normal text-gray-600">/mo</span></div>
              <ul className="mt-4 space-y-2 text-sm text-gray-700">
                <li className="flex items-center gap-2"><CheckIcon/>Global doc search</li>
                <li className="flex items-center gap-2"><CheckIcon/>Chat export (.md/.txt)</li>
                <li className="flex items-center gap-2"><CheckIcon/>Premium support</li>
              </ul>
              <Link to="/pricing" className="mt-6 inline-flex w-full items-center justify-center rounded-xl bg-gray-900 px-4 py-2.5 text-white hover:bg-black">Upgrade</Link>
            </div>
          </div>
        </div>
      </section>

      {/* Efficiency / ROI */}
      <section className="py-16">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 grid lg:grid-cols-2 gap-8 items-center">
          <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="text-xl font-semibold text-gray-900">Ship faster with retrieval-augmented answers</h3>
            <p className="mt-2 text-gray-700">Consultants spend hours searching across documents, emails, and chats. Neura turns that into minutes by indexing your uploads and giving sourced answers.</p>
            <ul className="mt-4 space-y-2 text-sm text-gray-700">
              <li className="flex items-center gap-2"><CheckIcon/>Cut search time by 60–80%</li>
              <li className="flex items-center gap-2"><CheckIcon/>Reduce rework with consistent answers</li>
              <li className="flex items-center gap-2"><CheckIcon/>Keep a single source of truth per project</li>
            </ul>
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="text-xl font-semibold text-gray-900">How it works</h3>
            <ol className="mt-3 list-decimal list-inside text-gray-700 space-y-1">
              <li>Sign up / log in</li>
              <li>Upload PDFs, docs, images (OCR)</li>
              <li>Ask a question</li>
              <li>Get answers with citations</li>
            </ol>
          </div>
        </div>
      </section>
    </>
  )
}
