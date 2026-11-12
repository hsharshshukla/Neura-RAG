import { API_BASE, readCookie } from './secureAxios';

const ALLOWED_EVENTS = new Set(['answer', 'citations', 'complete', 'error']);
const MAX_EVENT_CHARACTERS = 262144;

export class StreamingChatError extends Error {
  constructor(code, message, { retryable = false, status = null } = {}) {
    super(message || 'Verified answer streaming failed.');
    this.name = 'StreamingChatError';
    this.code = code || 'STREAM_UNAVAILABLE';
    this.retryable = Boolean(retryable);
    this.status = status;
  }
}

export class SSEParser {
  constructor(onEvent) {
    this.onEvent = onEvent;
    this.buffer = '';
  }

  feed(chunk) {
    this.buffer += chunk;
    if (this.buffer.length > MAX_EVENT_CHARACTERS) {
      throw new StreamingChatError('STREAM_EVENT_TOO_LARGE', 'The streaming response was invalid.');
    }
    let boundary = this.buffer.match(/\r?\n\r?\n/);
    while (boundary) {
      const block = this.buffer.slice(0, boundary.index);
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length);
      this.#parseBlock(block.replace(/\r\n/g, '\n'));
      boundary = this.buffer.match(/\r?\n\r?\n/);
    }
  }

  finish() {
    if (this.buffer.trim()) {
      throw new StreamingChatError('STREAM_TRUNCATED', 'The streaming response ended unexpectedly.');
    }
  }

  #parseBlock(block) {
    if (!block.trim()) return;
    let event = '';
    const data = [];
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue;
      const separator = line.indexOf(':');
      const field = separator < 0 ? line : line.slice(0, separator);
      const value = separator < 0 ? '' : line.slice(separator + 1).replace(/^ /, '');
      if (field === 'event') event = value;
      if (field === 'data') data.push(value);
    }
    if (!ALLOWED_EVENTS.has(event) || data.length === 0) {
      throw new StreamingChatError('STREAM_EVENT_INVALID', 'The streaming response was invalid.');
    }
    let payload;
    try {
      payload = JSON.parse(data.join('\n'));
    } catch {
      throw new StreamingChatError('STREAM_EVENT_INVALID', 'The streaming response was invalid.');
    }
    if (!payload || Array.isArray(payload) || typeof payload !== 'object') {
      throw new StreamingChatError('STREAM_EVENT_INVALID', 'The streaming response was invalid.');
    }
    this.onEvent(event, payload);
  }
}

export function validateStreamingEvent(state, event, payload) {
  if (state.complete || state.error) {
    throw new StreamingChatError('STREAM_EVENT_ORDER_INVALID', 'The streaming response was invalid.');
  }
  if (event === 'answer') {
    if (state.citations || typeof payload.chunk !== 'string' || !Number.isInteger(payload.index)) {
      throw new StreamingChatError('STREAM_EVENT_INVALID', 'The streaming response was invalid.');
    }
    state.answer = true;
  } else if (event === 'citations') {
    if (!state.answer || state.citations || !Array.isArray(payload.citations)) {
      throw new StreamingChatError('STREAM_EVENT_ORDER_INVALID', 'The streaming response was invalid.');
    }
    state.citations = true;
  } else if (event === 'complete') {
    if (!state.answer || !state.citations || payload.session_id == null) {
      throw new StreamingChatError('STREAM_EVENT_ORDER_INVALID', 'The streaming response was invalid.');
    }
    state.complete = true;
  } else if (event === 'error') {
    if (state.answer || state.citations || typeof payload.message !== 'string') {
      throw new StreamingChatError('STREAM_EVENT_ORDER_INVALID', 'The streaming response was invalid.');
    }
    state.error = true;
  }
}

export async function streamGroundedChat({
  message,
  sessionId,
  requestId,
  signal,
  onEvent,
  fetchImpl = fetch,
}) {
  const csrf = readCookie('csrf_token');
  const response = await fetchImpl(`${API_BASE}/chat/stream`, {
    method: 'POST',
    credentials: 'include',
    signal,
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    },
    body: JSON.stringify({
      message,
      request_id: requestId,
      ...(sessionId != null ? { session_id: sessionId } : {}),
    }),
  });

  if (!response.ok) {
    let body = {};
    try {
      body = await response.json();
    } catch {}
    const messageText = typeof body.detail === 'string'
      ? body.detail
      : 'Verified answer streaming is temporarily unavailable.';
    throw new StreamingChatError('STREAM_HTTP_ERROR', messageText, {
      retryable: response.status >= 500,
      status: response.status,
    });
  }
  if (!String(response.headers.get('content-type') || '').startsWith('text/event-stream')) {
    throw new StreamingChatError('STREAM_CONTENT_TYPE_INVALID', 'The streaming response was invalid.');
  }
  if (!response.body?.getReader) {
    throw new StreamingChatError('STREAM_UNSUPPORTED', 'Streaming is not supported by this browser.');
  }

  const state = { answer: false, citations: false, complete: false, error: false };
  const parser = new SSEParser((event, payload) => {
    validateStreamingEvent(state, event, payload);
    if (event === 'error') {
      throw new StreamingChatError(payload.code, payload.message, {
        retryable: payload.retryable,
      });
    }
    onEvent(event, payload);
  });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.feed(decoder.decode(value, { stream: true }));
    }
    parser.feed(decoder.decode());
    parser.finish();
    if (!state.complete) {
      throw new StreamingChatError('STREAM_TRUNCATED', 'The streaming response ended unexpectedly.');
    }
  } finally {
    reader.releaseLock();
  }
}
