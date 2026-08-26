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

export interface Brief {
  id: string;
  category: string;
  provider: string;
  model: string;
  verdict: Verdict | null;
  markdown: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  created_at: string;
}

export interface Assessment {
  verdict: Verdict | null;
  briefs: Brief[];
}

export interface JobState {
  id: string;
  upload_id: string;
  state:
    'queued' | 'parsing' | 'ruling' | 'analyzing' | 'done' | 'failed';
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

  async postUpload(
    file: File,
  ): Promise<{ upload_id: string; job_id: string }> {
    const fd = new FormData();
    fd.append('file', file);
    const resp = await fetch('/api/uploads', {
      method: 'POST',
      body: fd,
    });
    if (!resp.ok) {
      throw new Error(`POST /api/uploads returned ${resp.status}`);
    }
    return (await resp.json()) as {
      upload_id: string;
      job_id: string;
    };
  },
};
