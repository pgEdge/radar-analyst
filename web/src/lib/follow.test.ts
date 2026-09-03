/*
 * Following a job has two sources of truth: the event stream, which
 * is immediate, and the job record, which is authoritative. The
 * stream can drop; the record cannot. So the follower listens to the
 * stream for detail and polls the record for the outcome, and the
 * outcome is reported exactly once whichever arrives first.
 */

import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';

import type { JobState } from './api';
import { followJob, type FollowHandlers } from './follow';

class FakeSource {
  static instances: FakeSource[] = [];
  closed = false;
  private target = new EventTarget();

  constructor(public url: string) {
    FakeSource.instances.push(this);
  }
  addEventListener(type: string, fn: EventListener): void {
    this.target.addEventListener(type, fn);
  }
  close(): void {
    this.closed = true;
  }
  // Test hooks: the server, played by hand.
  message(data: unknown): void {
    this.target.dispatchEvent(
      new MessageEvent('message', { data: JSON.stringify(data) }),
    );
  }
  fail(): void {
    this.target.dispatchEvent(new Event('error'));
  }
}

function job(state: JobState['state'], error: string | null = null) {
  return {
    id: 'j',
    upload_id: 'u',
    state,
    phase: null,
    started_at: null,
    finished_at: null,
    error,
    ai_provider: null,
  } satisfies JobState;
}

function handlers(): FollowHandlers & {
  calls: Record<keyof FollowHandlers, unknown[][]>;
} {
  const calls = {
    onPhase: [] as unknown[][],
    onBrief: [] as unknown[][],
    onStatus: [] as unknown[][],
    onDone: [] as unknown[][],
    onError: [] as unknown[][],
  };
  return {
    calls,
    onPhase: (...a) => calls.onPhase.push(a),
    onBrief: (...a) => calls.onBrief.push(a),
    onStatus: (...a) => calls.onStatus.push(a),
    onDone: (...a) => calls.onDone.push(a),
    onError: (...a) => calls.onError.push(a),
  };
}

function start(
  h: FollowHandlers,
  getJob: (id: string) => Promise<JobState> = () =>
    Promise.resolve(job('analyzing')),
) {
  FakeSource.instances = [];
  return followJob(
    {
      jobId: 'j',
      createSource: (url) => new FakeSource(url),
      getJob,
      pollMs: 1000,
    },
    h,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('the stream', () => {
  it('is opened on the job events path', () => {
    const h = handlers();
    start(h);

    expect(FakeSource.instances[0].url).toBe('/api/jobs/j/events');
  });

  it('relays phases and briefs', () => {
    const h = handlers();
    start(h);
    const source = FakeSource.instances[0];

    source.message({
      type: 'phase',
      phase: 'analyzing Workload (3/5)',
    });
    source.message({
      type: 'brief',
      category: 'Workload',
      verdict: 'HEALTHY',
    });

    expect(h.calls.onPhase).toEqual([['analyzing Workload (3/5)']]);
    expect(h.calls.onBrief).toEqual([['Workload', 'HEALTHY']]);
  });

  it('reports done once and closes', () => {
    const h = handlers();
    start(h);
    const source = FakeSource.instances[0];

    source.message({ type: 'done' });
    source.message({ type: 'done' });

    expect(h.calls.onDone).toHaveLength(1);
    expect(source.closed).toBe(true);
  });

  it('reports a failure with its message', () => {
    const h = handlers();
    start(h);

    FakeSource.instances[0].message({
      type: 'error',
      message: 'archive is not a zip',
    });

    expect(h.calls.onError).toEqual([['archive is not a zip']]);
    expect(h.calls.onDone).toHaveLength(0);
  });

  it('says it is reconnecting on an error and keeps listening', () => {
    const h = handlers();
    start(h);
    const source = FakeSource.instances[0];

    source.fail();

    expect(h.calls.onStatus).toEqual([
      ['Connection lost; reconnecting…'],
    ]);
    expect(source.closed).toBe(false);
    expect(h.calls.onError).toHaveLength(0);
  });

  it('ignores lines that are not JSON', () => {
    const h = handlers();
    start(h);
    const source = FakeSource.instances[0];

    source['target'].dispatchEvent(
      new MessageEvent('message', { data: 'not json' }),
    );

    expect(h.calls.onError).toHaveLength(0);
    expect(source.closed).toBe(false);
  });
});

describe('the poll', () => {
  it('reports done from the job record when the stream is silent', async () => {
    const h = handlers();
    const states = [job('analyzing'), job('done')];
    start(h, () => Promise.resolve(states.shift() ?? job('done')));

    await vi.advanceTimersByTimeAsync(1000);
    expect(h.calls.onDone).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1000);

    expect(h.calls.onDone).toHaveLength(1);
    expect(FakeSource.instances[0].closed).toBe(true);
  });

  it('reports a failed job with its recorded error', async () => {
    const h = handlers();
    start(h, () =>
      Promise.resolve(job('failed', 'provider timed out')),
    );

    await vi.advanceTimersByTimeAsync(1000);

    expect(h.calls.onError).toEqual([['provider timed out']]);
  });

  it('stops once the stream has already reported the outcome', async () => {
    const h = handlers();
    const getJob = vi.fn(() => Promise.resolve(job('done')));
    start(h, getJob);

    FakeSource.instances[0].message({ type: 'done' });
    await vi.advanceTimersByTimeAsync(5000);

    expect(h.calls.onDone).toHaveLength(1);
    expect(getJob).not.toHaveBeenCalled();
  });

  it('survives a poll that fails and tries again', async () => {
    const h = handlers();
    let calls = 0;
    start(h, () => {
      calls += 1;
      return calls === 1
        ? Promise.reject(new Error('offline'))
        : Promise.resolve(job('done'));
    });

    await vi.advanceTimersByTimeAsync(2000);

    expect(h.calls.onDone).toHaveLength(1);
    expect(h.calls.onError).toHaveLength(0);
  });
});

describe('stopping', () => {
  it('closes the stream and ends the poll', async () => {
    const h = handlers();
    const getJob = vi.fn(() => Promise.resolve(job('analyzing')));
    const stop = start(h, getJob);

    stop();
    await vi.advanceTimersByTimeAsync(3000);

    expect(FakeSource.instances[0].closed).toBe(true);
    expect(getJob).not.toHaveBeenCalled();
  });
});
