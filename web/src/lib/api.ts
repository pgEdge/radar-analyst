/*
 * Thin fetch wrapper around the radar-analyst JSON API. All requests go
 * to same-origin paths (/api/...). In dev, Astro's proxy forwards
 * those to the Python backend on localhost:8080.
 */

export interface UploadSummary {
  id: string;
  filename: string;
  storage_url: string;
  size_bytes: number;
  sha256: string;
  hostname: string | null;
  archive_timestamp: string | null;
  created_at: string;
  state: JobState['state'] | null;
  verdict: Verdict | null;
}

export interface Snapshot {
  hostname?: string;
  os?: string;
  pg_version?: string;
  total_ram?: string;
  parsed_kinds?: string[];
  unknown_entries?: string[];
  [key: string]: unknown;
}

export type Verdict = 'HEALTHY' | 'WARNING' | 'CRITICAL' | 'UNKNOWN';

export interface Finding {
  rule_id: string;
  severity: string;
  title: string;
  detail: string | null;
}

export interface Brief {
  id: string;
  category: string;
  provider: string | null;
  model: string | null;
  verdict: Verdict | null;
  markdown: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  created_at: string;
  findings: Finding[];
}

export interface Assessment {
  verdict: Verdict | null;
  briefs: Brief[];
}

export interface JobState {
  id: string;
  upload_id: string;
  state: 'queued' | 'parsing' | 'analyzing' | 'done' | 'failed';
  phase: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  ai_provider: string | null;
}

export interface ProviderInfo {
  name: string;
  label: string;
  available: boolean;
  model: string;
  reason?: string;
}

export interface ConfigResponse {
  providers: ProviderInfo[];
  default: string;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(path, {
    headers: { Accept: 'application/json' },
  });
  if (!resp.ok) {
    throw new Error(
      `GET ${path} returned ${resp.status} ${resp.statusText}`,
    );
  }
  return (await resp.json()) as T;
}

export const api = {
  listUploads(
    limit = 50,
    offset = 0,
  ): Promise<{ items: UploadSummary[] }> {
    return getJson(`/api/uploads?limit=${limit}&offset=${offset}`);
  },

  getUpload(id: string): Promise<UploadSummary> {
    return getJson(`/api/uploads/${id}`);
  },

  getSnapshot(id: string): Promise<Snapshot> {
    return getJson(`/api/uploads/${id}/snapshot`);
  },

  getAssessment(id: string): Promise<Assessment> {
    return getJson(`/api/uploads/${id}/assessment`);
  },

  getJob(id: string): Promise<JobState> {
    return getJson(`/api/jobs/${id}`);
  },

  getConfig(): Promise<ConfigResponse> {
    return getJson('/api/config');
  },

  async deleteUpload(id: string, token: string): Promise<void> {
    const resp = await fetch(`/api/uploads/${id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (resp.ok) return;
    if (resp.status === 401) {
      throw new Error('The admin token was not accepted.');
    }
    if (resp.status === 503) {
      throw new Error('Deleting is not configured on this analyst.');
    }
    throw new Error(
      `DELETE /api/uploads/${id} returned ${resp.status}`,
    );
  },

  async assessAgain(id: string): Promise<UploadReceipt> {
    const resp = await fetch(`/api/uploads/${id}/assess`, {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
    if (resp.ok) return (await resp.json()) as UploadReceipt;
    if (resp.status === 409) {
      throw new Error('This upload is still being assessed.');
    }
    throw new Error(
      `POST /api/uploads/${id}/assess returned ${resp.status}`,
    );
  },

  postUpload(
    file: File,
    onProgress?: (fraction: number) => void,
  ): Promise<UploadReceipt> {
    // XMLHttpRequest rather than fetch: only it reports how much of
    // the body has been sent, and a real archive can run to 100 MB.
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/uploads');
      if (onProgress) {
        xhr.upload.addEventListener('progress', (e: ProgressEvent) => {
          if (e.lengthComputable && e.total > 0) {
            onProgress(e.loaded / e.total);
          }
        });
      }
      xhr.addEventListener('load', () => {
        if (xhr.status < 200 || xhr.status >= 300) {
          const reason = refusalReason(xhr.responseText);
          reject(
            new Error(
              `POST /api/uploads returned ${xhr.status}` +
                (reason ? `: ${reason}` : ''),
            ),
          );
          return;
        }
        try {
          resolve(JSON.parse(xhr.responseText) as UploadReceipt);
        } catch {
          reject(
            new Error('POST /api/uploads returned an unreadable reply'),
          );
        }
      });
      xhr.addEventListener('error', () => {
        reject(
          new Error(
            'The upload did not reach the analyst. Check that it is ' +
              'still running, then try again.',
          ),
        );
      });
      const fd = new FormData();
      fd.append('file', file);
      xhr.send(fd);
    });
  },
};

export interface UploadReceipt {
  upload_id: string;
  job_id: string;
}

// A refusal carries its reason as {"detail": "..."}; anything else is
// shown as it came, trimmed to one line.
function refusalReason(text: string): string {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === 'string') {
      return parsed.detail;
    }
  } catch {
    // Not JSON; fall through to the raw text.
  }
  return text.split('\n')[0].slice(0, 200);
}
