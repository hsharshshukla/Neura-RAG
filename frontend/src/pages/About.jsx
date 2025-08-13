export default function About(){
    return (
      <section className="py-16">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-semibold text-gray-900">About Neura</h1>
          <p className="mt-3 text-gray-700">Neura is a GPT-powered assistant with OCR and vector search, built on a React + FastAPI stack. It’s designed to help ECM (OpenText) consultants ship faster by turning messy repositories into precise answers.</p>
          <div className="mt-6 grid md:grid-cols-2 gap-6">
            <div className="rounded-2xl border border-gray-200 bg-white p-6">
              <h3 className="font-medium text-gray-900">Architecture</h3>
              <p className="mt-2 text-sm text-gray-700">User → React UI → FastAPI → VectorDB + GPT → Response.</p>
            </div>
            <div className="rounded-2xl border border-gray-200 bg-white p-6">
              <h3 className="font-medium text-gray-900">Key Features</h3>
              <ul className="mt-2 list-disc list-inside text-sm text-gray-700 space-y-1">
                <li>OCR & vector search with metadata filters</li>
                <li>Session-scoped vs global search by tier</li>
                <li>Chat history, export for Pro</li>
              </ul>
            </div>
          </div>
        </div>
      </section>
    )
  }
  