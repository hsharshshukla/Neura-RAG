import React from 'react';

export function CitationList({ citations = [], onSelect }) {
  if (!citations.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2" aria-label="Verified citations">
      {citations.map((citation) => (
        <button
          type="button"
          key={citation.evidence_id}
          onClick={() => onSelect(citation)}
          className="rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-800 hover:bg-indigo-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          aria-label={`Inspect citation ${citation.evidence_id}: ${citation.title || 'Approved evidence'}`}
        >
          [{citation.evidence_id}] {citation.title || 'Approved evidence'}
        </button>
      ))}
    </div>
  );
}

function locatorText(locator = {}) {
  return Object.entries(locator)
    .map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`)
    .join(', ');
}

export function CitationInspector({ citation, onClose }) {
  if (!citation) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 md:items-center md:p-6" role="presentation">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="citation-title"
        className="max-h-[85vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl md:max-w-xl md:rounded-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-indigo-600">
              Verified citation [{citation.evidence_id}]
            </div>
            <h2 id="citation-title" className="mt-1 text-lg font-semibold text-gray-900">
              {citation.title || 'Approved TKP evidence'}
            </h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg px-2 py-1 text-gray-600 hover:bg-gray-100" aria-label="Close citation details">
            Close
          </button>
        </div>

        {citation.relevant_section && (
          <div className="mt-4">
            <div className="text-xs font-semibold text-gray-500">Relevant section</div>
            <div className="mt-1 text-sm text-gray-900">{citation.relevant_section}</div>
          </div>
        )}
        {citation.heading_path?.length > 0 && (
          <div className="mt-3 text-xs text-gray-600">{citation.heading_path.join(' / ')}</div>
        )}

        <div className="mt-4 space-y-3">
          {(citation.sources || []).map((source) => (
            <div key={source.source_fragment_id} className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
              <div><strong>Source:</strong> {source.source_id}</div>
              <div className="mt-1"><strong>Version:</strong> {source.source_version_id}</div>
              {source.source_revision_number != null && (
                <div className="mt-1"><strong>Revision:</strong> {source.source_revision_number}</div>
              )}
              {Object.keys(source.locator || {}).length > 0 && (
                <div className="mt-1"><strong>Location:</strong> {locatorText(source.locator)}</div>
              )}
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-gray-500">
          This view contains verified lineage metadata only. Document content remains protected by workspace authorization.
        </p>
      </section>
    </div>
  );
}
