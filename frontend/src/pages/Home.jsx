import { Link } from 'react-router-dom'
import Footer from "../components/Footer";

function CheckIcon(props){
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={props.className || 'h-5 w-5'}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M5 13l4 4L19 7"
      />
    </svg>
  )
}

export default function Home(){
  return (
    <>
      {/* Hero */}
      <section className="bg-gradient-to-b from-violet-50 via-sky-50 to-white text-slate-900">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-16 lg:py-20 grid md:grid-cols-2 gap-10 lg:gap-14 items-center">
          <div>
            <p className="inline-flex items-center rounded-full border border-violet-100 bg-white/80 px-3 py-1 text-xs font-medium text-slate-700 shadow-sm mb-4">
              Built for ECM / OpenText consultants
            </p>

            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight leading-tight">
              Neura — your AI copilot for{" "}
              <span className="text-indigo-600">ECM projects</span>
            </h1>

            <p className="mt-4 text-base sm:text-lg text-slate-700 max-w-xl">
              Upload your project documents once and stop hunting through PDFs, SOWs, and emails.
              Neura uses OCR, vector search, and the latest GPT models to give sourced answers for
              OpenText and other ECM-heavy work.
            </p>

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Link
                to="/pricing"
                className="inline-flex items-center rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 transition-colors"
              >
                See plans
              </Link>
              <span className="text-xs sm:text-sm text-slate-600">
                Neura answers only from your project content. No generic internet noise.
              </span>
            </div>

            <div className="mt-6 flex flex-wrap gap-3 text-xs sm:text-sm text-slate-700">
              <span className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 border border-violet-100 shadow-sm">
                <CheckIcon className="h-4 w-4 text-indigo-500" />
                OCR on PDFs, images &amp; scans
              </span>
              <span className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 border border-violet-100 shadow-sm">
                <CheckIcon className="h-4 w-4 text-indigo-500" />
                No more manual document digging
              </span>
              <span className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 border border-violet-100 shadow-sm">
                <CheckIcon className="h-4 w-4 text-indigo-500" />
                Secure &amp; private by design
              </span>
            </div>
          </div>

          {/* Chat preview card */}
          <div className="md:pl-4 lg:pl-6">
            <div className="rounded-3xl border border-violet-100 bg-white/80 backdrop-blur-sm p-4 sm:p-5 shadow-xl">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  <span>Project workspace: xECM upgrade</span>
                </div>
                <span className="text-[10px] px-2 py-1 rounded-full bg-violet-50 text-slate-500 border border-violet-100">
                  Sample chat
                </span>
              </div>

              <div className="rounded-2xl bg-slate-50 border border-violet-100 p-3 sm:p-4 space-y-3">
                {/* User message – RIGHT aligned */}
                <div className="flex justify-end gap-2">
                  <div className="flex-1 max-w-[80%]">
                    <p className="text-xs uppercase tracking-wide text-slate-500 mb-1 text-right">
                      You
                    </p>
                    <div className="inline-block rounded-2xl bg-white px-3 py-2 text-xs sm:text-sm text-slate-900 border border-violet-100 ml-auto text-right">
                      List all prerequisites for upgrading xECM to 21.x from my docs and call out
                      any missing information.
                    </div>
                  </div>
                  <div className="mt-1 h-6 w-6 shrink-0 rounded-full bg-indigo-500 text-[11px] flex items-center justify-center text-white">
                    U
                  </div>
                </div>

                {/* Neura message – LEFT aligned */}
                <div className="flex gap-2">
                  <div className="mt-1 h-6 w-6 shrink-0 rounded-full bg-slate-100 text-[11px] flex items-center justify-center text-indigo-500 border border-violet-100">
                    N
                  </div>
                  <div className="flex-1 max-w-[80%]">
                    <p className="text-xs uppercase tracking-wide text-slate-500 mb-1">
                      Neura
                    </p>
                    <div className="inline-block rounded-2xl bg-slate-900 text-slate-50 px-3 py-2 text-xs sm:text-sm">
                      <p className="mb-1">
                        Here are the key prerequisites I found across your project documentation:
                      </p>
                      <ul className="list-disc list-inside space-y-0.5">
                        <li>Content Server upgraded to 23.x with patch bundle Q3 applied</li>
                        <li>xECM 21.x compatible SAP add-on installed in QA &amp; PROD</li>
                        <li>Minimum database backup retention of 30 days</li>
                      </ul>
                      <p className="mt-2 text-[11px] text-slate-200">
                        Missing: confirmed downtime window and rollback SOW for PROD.
                      </p>
                      <p className="mt-1 text-[10px] text-slate-300">
                        Sources: SOW_v3_final.pdf, Upgrade_Readiness_Checklist.xlsx
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              <p className="mt-3 text-[11px] text-slate-500">
                Neura answers only from your uploaded content. No internet browsing, no guessing.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Why Neura */}
      <section className="py-16 bg-gradient-to-b from-violet-50 via-sky-50 to-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-2xl sm:text-3xl font-semibold text-slate-900 tracking-tight">
                Why Neura
              </h2>
              <p className="mt-2 text-sm sm:text-base text-slate-700 max-w-3xl">
                Built for ECM (OpenText) consultants who live inside content-heavy projects and need
                answers they can trace back to their own docs.
              </p>
            </div>
          </div>

          <div className="mt-8 grid gap-6 md:grid-cols-2">
            {[
              {
                title: 'OCR + unified search',
                desc: 'Upload SOWs, design docs, tickets, and screenshots. Neura OCRs and indexes everything so you can search it all at once instead of opening files one by one.',
              },
              {
                title: 'Neura Engine (GPT-powered)',
                desc: 'Your question is cleaned up, expanded, and matched with the right chunks before the latest GPT models respond — better prompts, better context, better answers.',
              },
              {
                title: 'Chat history & recall',
                desc: 'Keep a running memory of each project. Revisit threads and reuse answers instead of rewriting them for every email or meeting.',
              },
              {
                title: 'Security & privacy by default',
                desc: 'Project data stays scoped to your account. Stored securely, not used to train models, with workspace-level access control.',
              },
            ].map((f, i) => (
              <div
                key={i}
                className="rounded-2xl border border-violet-100 bg-white p-5 sm:p-6 shadow-sm hover:border-violet-300 transition-colors"
              >
                <h3 className="text-base sm:text-lg font-semibold text-slate-900 mb-2">
                  {f.title}
                </h3>
                <p className="text-sm text-slate-700 leading-relaxed">
                  {f.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Ship faster – centered card */}
      <section className="py-16 bg-gradient-to-b from-violet-50 via-sky-50 to-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mx-auto">
            <div className="rounded-2xl border border-violet-100 bg-white p-6 sm:p-7 shadow-sm">
              <h3 className="text-xl sm:text-2xl font-semibold text-slate-900 tracking-tight mb-2">
                Ship faster with retrieval-augmented answers
              </h3>
              <p className="mt-1 text-sm sm:text-base text-slate-700">
                Most ECM work doesn&apos;t fail on logic — it stalls on finding the right sentence in
                the right PDF. Neura turns scattered docs into a single, searchable, GPT-powered
                workspace.
              </p>

              <div className="mt-4 flex flex-wrap gap-2 text-[11px] sm:text-xs text-slate-700">
                <span className="inline-flex items-center gap-2 rounded-full bg-violet-50 px-3 py-1 border border-violet-100">
                  <CheckIcon className="h-3.5 w-3.5 text-indigo-500" />
                  60–80% less time searching docs
                </span>
                <span className="inline-flex items-center gap-2 rounded-full bg-violet-50 px-3 py-1 border border-violet-100">
                  <CheckIcon className="h-3.5 w-3.5 text-indigo-500" />
                  One workspace for SOWs, configs &amp; tickets
                </span>
                <span className="inline-flex items-center gap-2 rounded-full bg-violet-50 px-3 py-1 border border-violet-100">
                  <CheckIcon className="h-3.5 w-3.5 text-indigo-500" />
                  Answers always linked to sources
                </span>
              </div>

              <ul className="mt-4 space-y-2 text-sm text-slate-700">
                <li className="flex items-center gap-2">
                  <CheckIcon className="h-4 w-4 text-indigo-500" />
                  Stop reopening the same five PDFs all week
                </li>
                <li className="flex items-center gap-2">
                  <CheckIcon className="h-4 w-4 text-indigo-500" />
                  Reuse past answers instead of retyping them for every email
                </li>
                <li className="flex items-center gap-2">
                  <CheckIcon className="h-4 w-4 text-indigo-500" />
                  Keep a shared view of what&apos;s true for each project
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Built for real-world – centered card */}
      <section className="py-16 bg-gradient-to-b from-violet-50 via-sky-50 to-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mx-auto">
            <div className="rounded-2xl border border-violet-100 bg-white p-6 sm:p-7 shadow-sm">
              <h3 className="text-xl sm:text-2xl font-semibold text-slate-900 tracking-tight mb-2">
                Built for real-world delivery work
              </h3>
              <p className="mt-1 text-sm sm:text-base text-slate-700">
                Neura is shaped around how ECM consultants actually work — juggling upgrades, issues,
                and stakeholders across multiple projects.
              </p>
              <ul className="mt-4 space-y-2 text-sm text-slate-700">
                <li className="flex items-start gap-2">
                  <CheckIcon className="h-4 w-4 text-indigo-500 mt-0.5" />
                  <span>
                    Drafting upgrade notes? Ask Neura to pull all risks and prerequisites from your
                    own documentation.
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckIcon className="h-4 w-4 text-indigo-500 mt-0.5" />
                  <span>
                    Joining a project late? Skim the chat and sources instead of reading every SOW
                    version end to end.
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckIcon className="h-4 w-4 text-indigo-500 mt-0.5" />
                  <span>
                    Handing over to another consultant? Export key chats and links as a quick
                    project brief.
                  </span>
                </li>
              </ul>
              <p className="mt-3 text-xs text-slate-600">
                Designed around today&apos;s OpenText work, with room to grow into more ECM stacks.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Neura product suite – moved after Built for real-world */}
      <section className="py-16 bg-gradient-to-b from-violet-50 via-sky-50 to-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-2xl sm:text-3xl font-semibold text-slate-900 tracking-tight">
                Neura AI product suite <span className="text-xs sm:text-sm text-indigo-600">(Coming Soon)</span>
              </h2>
              <p className="mt-2 text-sm sm:text-base text-slate-700 max-w-3xl">
                Alongside the Neura copilot, we&apos;re building specialised AI tools that sit on top of
                your content, configs, and ERP landscape.
              </p>
            </div>
          </div>

          <div className="mt-8 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {[
              {
                name: 'BeastSearch',
                label: 'Vector search for enterprise content',
                desc: 'A vector database–powered search engine that lets you query PDFs, emails, tickets, and configs in natural language and get semantically relevant results across OpenText and SAP content.',
              },
              {
                name: 'AI Gateway',
                label: 'On-demand GenAI usage layer',
                desc: 'A managed gateway around advanced language models that gives teams pay-as-you-go access with simple refills, centralised billing, and built-in guardrails for enterprise use.',
              },
              {
                name: 'Contract Creator Bot',
                label: 'ERP-ready contract generator',
                desc: 'Users fill a few mandatory fields; the bot pulls historical contracts from a vector store, drafts a contract, returns a structured JSON for approval, and on approval creates it in the ERP.',
              },
              {
                name: 'Invoice Posting Bot',
                label: 'AI-assisted invoice processor',
                desc: 'Combines user inputs with historical posting data and configs, generates an ERP-ready invoice posting payload in JSON, and posts after human approval.',
              },
              {
                name: 'Upgrade & Impact Advisor',
                label: 'Upgrade readiness & risk analysis ',
                desc: 'An AI assistant that ingests your current ECM landscape, release notes, and project documentation to assess upgrade readiness, highlight breaking changes, and summarise risks and prerequisites for each target version.',
              },
              {
                name: 'NeuArchive',
                label: 'Cloud archive for SAP data',
                desc: 'A backend cloud archiving solution for SAP structured and unstructured data, offloading cold data from primary systems while keeping it searchable via AI and vector search.',
              },
            ].map((p, i) => (
              <div
                key={i}
                className="rounded-2xl border border-violet-100 bg-white p-5 sm:p-6 shadow-sm hover:border-violet-300 transition-colors flex flex-col"
              >
                <div className="mb-2">
                  <h3 className="text-base sm:text-lg font-semibold text-slate-900">
                    {p.name}
                  </h3>
                  <p className="text-xs sm:text-[13px] text-indigo-700 mt-0.5">
                    {p.label}
                  </p>
                </div>
                <p className="text-sm text-slate-700 leading-relaxed flex-1">
                  {p.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Footer />
    </>
  )
}
