/*
 * Follows one assessment job for the progress page. The event stream
 * gives the detail as it happens; the job record, polled alongside,
 * gives the outcome even if the stream never recovers from a drop.
 * Whichever reports the outcome first wins, and it is reported once.
 */

import { api, type JobState } from './api';

export interface FollowHandlers {
  onPhase(phase: string): void;
  onBrief(category: string, verdict: string): void;
  onStatus(text: string): void;
  onDone(): void;
  onError(message: string): void;
}

export interface EventSourceLike {
  addEventListener(
    type: string,
    listener: (event: Event) => void,
  ): void;
  close(): void;
}

export interface FollowOptions {
  jobId: string;
  createSource?: (url: string) => EventSourceLike;
  getJob?: (id: string) => Promise<JobState>;
  pollMs?: number;
}

export const RECONNECTING = 'Connection lost; reconnecting…';

interface StreamEvent {
  type?: string;
  phase?: string;
  category?: string;
  verdict?: string;
  message?: string;
}

export function followJob(
  options: FollowOptions,
  handlers: FollowHandlers,
): () => void {
  const {
    jobId,
    createSource = (url) => new EventSource(url),
    getJob = (id) => api.getJob(id),
    pollMs = 5000,
  } = options;

  let finished = false;
  const source = createSource(`/api/jobs/${jobId}/events`);

  // `timer` is declared below, once the handlers it drives exist; it
  // is only read here after the interval has started.
  const stop = (): void => {
    finished = true;
    source.close();
    clearInterval(timer);
  };
  const done = (): void => {
    if (finished) return;
    stop();
    handlers.onDone();
  };
  const failed = (message: string): void => {
    if (finished) return;
    stop();
    handlers.onError(message);
  };

  source.addEventListener('message', (event) => {
    let parsed: StreamEvent;
    try {
      parsed = JSON.parse(
        (event as MessageEvent<string>).data,
      ) as StreamEvent;
    } catch {
      return;
    }
    switch (parsed.type) {
      case 'phase':
        handlers.onPhase(parsed.phase ?? 'working');
        break;
      case 'brief':
        handlers.onBrief(
          parsed.category ?? '',
          parsed.verdict ?? 'UNKNOWN',
        );
        break;
      case 'done':
        done();
        break;
      case 'error':
        failed(parsed.message ?? 'unknown error');
        break;
      default:
        break;
    }
  });

  // The browser reconnects an EventSource by itself; the page only
  // has to say so. The outcome still arrives through the poll.
  source.addEventListener('error', () => {
    if (!finished) handlers.onStatus(RECONNECTING);
  });

  const timer = setInterval(() => {
    if (finished) return;
    getJob(jobId)
      .then((job) => {
        if (finished) return;
        if (job.state === 'done') done();
        else if (job.state === 'failed')
          failed(job.error ?? 'job failed');
      })
      .catch(() => {
        // A poll that fails is retried on the next tick.
      });
  }, pollMs);

  return stop;
}
