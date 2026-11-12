import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { CitationInspector, CitationList } from './Citations';

const citation = {
  evidence_id: 'E1',
  title: 'Approved operating procedure',
  relevant_section: 'Recovery steps',
  heading_path: ['Operations', 'Recovery steps'],
  sources: [{
    source_fragment_id: 'fragment-1',
    source_id: 'source-1',
    source_version_id: 'version-2',
    source_revision_number: 3,
    locator: { page_start: 4, page_end: 5 },
  }],
};

test('renders a clickable verified citation reference', () => {
  const markup = renderToStaticMarkup(
    <CitationList citations={[citation]} onSelect={() => {}} />,
  );
  expect(markup).toContain('<button');
  expect(markup).toContain('[E1] Approved operating procedure');
  expect(markup).toContain('Inspect citation E1');
});

test('renders approved lineage metadata without document content', () => {
  const markup = renderToStaticMarkup(
    <CitationInspector citation={citation} onClose={() => {}} />,
  );
  expect(markup).toContain('Recovery steps');
  expect(markup).toContain('source-1');
  expect(markup).toContain('page start: 4');
  expect(markup).toContain('Document content remains protected');
  expect(markup).not.toContain('raw private document text');
});
