/*
 * The console is a pure consumer of the JSON API, so what it has to
 * get right is the request it sends and how it reports a refusal.
 * Every path here is same-origin: a leading slash, never a host.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';

interface Recorded {
  url: string;
  init: RequestInit | undefined;
}

function stubFetch(
  response: Partial<Response> & { json?: () => unknown },
): Recorded[] {
  const calls: Recorded[] = [];
  const fake = vi.fn((url: string | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return Promise.resolve({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({}),
      ...response,
    } as Response);
  });
  vi.stubGlobal('fetch', fake);
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('request shape', () => {
  it('asks for JSON on every read', async () => {
    const calls = stubFetch({});

    await api.getConfig();

    expect(calls).toHaveLength(1);
    const headers = calls[0].init?.headers as
      Record<string, string> | undefined;
    expect(headers?.Accept).toBe('application/json');
  });

  it('keeps every path same-origin', async () => {
    const calls = stubFetch({});

    await api.getConfig();
    await api.getUpload('abc');
    await api.getSnapshot('abc');
    await api.getAssessment('abc');
    await api.getJob('def');

    expect(calls).toHaveLength(5);
    for (const call of calls) {
      expect(call.url.startsWith('/api/')).toBe(true);
    }
  });

  it('paginates uploads with limit and offset', async () => {
    const calls = stubFetch({});

    await api.listUploads(10, 20);

    expect(calls[0].url).toBe('/api/uploads?limit=10&offset=20');
  });

  it('defaults to the first fifty uploads', async () => {
    const calls = stubFetch({});

    await api.listUploads();

    expect(calls[0].url).toBe('/api/uploads?limit=50&offset=0');
  });

  it('puts the id in the path, not a query', async () => {
    const calls = stubFetch({});

    await api.getAssessment('9d6691b1');

    expect(calls[0].url).toBe('/api/uploads/9d6691b1/assessment');
  });
});

describe('failure reporting', () => {
  it('names the path and status when a read is refused', async () => {
    stubFetch({
      ok: false,
      status: 404,
      statusText: 'Not Found',
    });

    await expect(api.getUpload('missing')).rejects.toThrow(
      /\/api\/uploads\/missing returned 404 Not Found/,
    );
  });

  it('reports the status when an upload is refused', async () => {
    stubFetch({ ok: false, status: 415, statusText: 'x' });
    const file = new File(['not a zip'], 'x.txt');

    await expect(api.postUpload(file)).rejects.toThrow(
      /POST \/api\/uploads returned 415/,
    );
  });
});

describe('uploading', () => {
  it('posts the file as multipart under "file"', async () => {
    const calls = stubFetch({
      json: () => Promise.resolve({ upload_id: 'u', job_id: 'j' }),
    });
    const file = new File(['zip bytes'], 'radar-host.zip');

    const result = await api.postUpload(file);

    expect(calls[0].url).toBe('/api/uploads');
    expect(calls[0].init?.method).toBe('POST');
    const body = calls[0].init?.body as FormData;
    expect(body.get('file')).toBe(file);
    expect(result).toEqual({ upload_id: 'u', job_id: 'j' });
  });

  it('sets no Content-Type, so the boundary is generated', async () => {
    // Setting it by hand is the classic multipart mistake: the
    // browser can no longer append the boundary and the server
    // cannot parse the body.
    const calls = stubFetch({
      json: () => Promise.resolve({ upload_id: 'u', job_id: 'j' }),
    });

    await api.postUpload(new File(['x'], 'a.zip'));

    const headers = calls[0].init?.headers as
      Record<string, string> | undefined;
    expect(headers).toBeUndefined();
  });
});
