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
});

class FakeXhr {
  static instances: FakeXhr[] = [];
  method = '';
  url = '';
  headers: Record<string, string> = {};
  body: unknown = undefined;
  status = 0;
  responseText = '';
  upload = new EventTarget();
  private target = new EventTarget();

  constructor() {
    FakeXhr.instances.push(this);
  }
  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string): void {
    this.headers[name.toLowerCase()] = value;
  }
  addEventListener(type: string, fn: EventListener): void {
    this.target.addEventListener(type, fn);
  }
  send(body: unknown): void {
    this.body = body;
  }
  // Test hooks: the network, played by hand.
  progress(loaded: number, total: number): void {
    // Node has no ProgressEvent; a plain Event carrying the same
    // fields is what the listener reads.
    const event = Object.assign(new Event('progress'), {
      lengthComputable: true,
      loaded,
      total,
    });
    this.upload.dispatchEvent(event);
  }
  respond(status: number, text: string): void {
    this.status = status;
    this.responseText = text;
    this.target.dispatchEvent(new Event('load'));
  }
  fail(): void {
    this.target.dispatchEvent(new Event('error'));
  }
}

function stubXhr(): typeof FakeXhr {
  FakeXhr.instances = [];
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
  return FakeXhr;
}

describe('uploading', () => {
  it('posts the file as multipart under "file"', async () => {
    const Xhr = stubXhr();
    const file = new File(['zip bytes'], 'radar-host.zip');

    const pending = api.postUpload(file);
    const xhr = Xhr.instances[0];
    xhr.respond(201, '{"upload_id":"u","job_id":"j"}');

    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe('/api/uploads');
    expect((xhr.body as FormData).get('file')).toBe(file);
    await expect(pending).resolves.toEqual({
      upload_id: 'u',
      job_id: 'j',
    });
  });

  it('sets no Content-Type, so the boundary is generated', async () => {
    // Setting it by hand is the classic multipart mistake: the
    // browser can no longer append the boundary and the server
    // cannot parse the body.
    const Xhr = stubXhr();

    const pending = api.postUpload(new File(['x'], 'a.zip'));
    Xhr.instances[0].respond(201, '{"upload_id":"u","job_id":"j"}');
    await pending;

    expect(Xhr.instances[0].headers['content-type']).toBeUndefined();
  });

  it('reports upload progress as a fraction of the body', async () => {
    const Xhr = stubXhr();
    const seen: number[] = [];

    const pending = api.postUpload(new File(['x'], 'a.zip'), (f) => {
      seen.push(f);
    });
    const xhr = Xhr.instances[0];
    xhr.progress(50, 200);
    xhr.progress(200, 200);
    xhr.respond(201, '{"upload_id":"u","job_id":"j"}');
    await pending;

    expect(seen).toEqual([0.25, 1]);
  });

  it('reports the status and the reason when an upload is refused', async () => {
    const Xhr = stubXhr();

    const pending = api.postUpload(new File(['not a zip'], 'x.txt'));
    Xhr.instances[0].respond(415, '{"detail":"not a zip archive"}');

    await expect(pending).rejects.toThrow(
      /POST \/api\/uploads returned 415.*not a zip archive/,
    );
  });

  it('says so when the upload never reaches the analyst', async () => {
    const Xhr = stubXhr();

    const pending = api.postUpload(new File(['x'], 'a.zip'));
    Xhr.instances[0].fail();

    await expect(pending).rejects.toThrow(/did not reach the analyst/);
  });
});
