import { TextDecoder, TextEncoder } from 'util';

jest.mock('./secureAxios', () => ({
  API_BASE: '/api/v1',
  readCookie: () => '',
}));

import {
  SSEParser,
  StreamingChatError,
  streamGroundedChat,
  validateStreamingEvent,
} from './streamingChat';

global.TextDecoder = TextDecoder;
global.TextEncoder = TextEncoder;

function responseFrom(chunks, { contentType = 'text/event-stream', status = 200 } = {}) {
  let index = 0;
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => contentType },
    json: async () => ({}),
    body: {
      getReader: () => ({
        read: async () => index < chunks.length
          ? { done: false, value: new TextEncoder().encode(chunks[index++]) }
          : { done: true, value: undefined },
        releaseLock: jest.fn(),
      }),
    },
  };
}

test('parses split SSE frames and completes the validated lifecycle', async () => {
  const received = [];
  const frames = [
    'event: answer\ndata: {"index":0,"chunk":"Approved "}\n\n',
    'event: answer\ndata: {"index":1,"chunk":"answer [E1]"}\n\n',
    'event: citations\ndata: {"citations":[{"evidence_id":"E1"}]}\n\n',
    'event: complete\ndata: {"session_id":7}\n\n',
  ].join('');
  const fetchImpl = jest.fn(async () => responseFrom([
    frames.slice(0, 17),
    frames.slice(17, 73),
    frames.slice(73),
  ]));

  await streamGroundedChat({
    message: 'question',
    requestId: 'request-1',
    signal: new AbortController().signal,
    onEvent: (event, payload) => received.push([event, payload]),
    fetchImpl,
  });

  expect(received.map(([event]) => event)).toEqual([
    'answer',
    'answer',
    'citations',
    'complete',
  ]);
  expect(received.filter(([event]) => event === 'answer').map(([, data]) => data.chunk).join(''))
    .toBe('Approved answer [E1]');
  expect(fetchImpl.mock.calls[0][1].credentials).toBe('include');
});

test('rejects malformed JSON and truncated streams', async () => {
  const parser = new SSEParser(jest.fn());
  expect(() => parser.feed('event: answer\ndata: not-json\n\n')).toThrow(StreamingChatError);

  await expect(streamGroundedChat({
    message: 'question',
    requestId: 'request-2',
    signal: new AbortController().signal,
    onEvent: jest.fn(),
    fetchImpl: async () => responseFrom([
      'event: answer\ndata: {"index":0,"chunk":"partial"}\n\n',
    ]),
  })).rejects.toMatchObject({ code: 'STREAM_TRUNCATED' });
});

test('rejects citations before answer and errors after content', () => {
  const state = { answer: false, citations: false, complete: false, error: false };
  expect(() => validateStreamingEvent(state, 'citations', { citations: [] }))
    .toThrow(StreamingChatError);

  const second = { answer: false, citations: false, complete: false, error: false };
  validateStreamingEvent(second, 'answer', { index: 0, chunk: 'validated' });
  expect(() => validateStreamingEvent(second, 'error', { message: 'late error' }))
    .toThrow(StreamingChatError);
});
