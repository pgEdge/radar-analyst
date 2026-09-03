/*
 * How the console renders raw fields: a size, a time, and the one
 * chip that says where an assessment stands. Decided once, here.
 */

export type Tone =
  'healthy' | 'warning' | 'critical' | 'info' | 'unknown';

export interface Chip {
  label: string;
  tone: Tone;
}

const RUNNING = new Set(['queued', 'parsing', 'ruling', 'analyzing']);

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function formatWhen(
  iso: string | null,
  locale?: string,
  timeZone?: string,
): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone,
  });
}

export function toneFor(verdict: string): Tone {
  switch (verdict) {
    case 'HEALTHY':
      return 'healthy';
    case 'WARNING':
      return 'warning';
    case 'CRITICAL':
      return 'critical';
    default:
      return 'unknown';
  }
}

// A running job outranks any verdict it has produced so far, and a
// failed one has no verdict to show; otherwise the roll-up speaks.
export function statusChip(
  state: string | null,
  verdict: string | null,
): Chip {
  if (state && RUNNING.has(state)) {
    return { label: 'Assessing…', tone: 'info' };
  }
  if (state === 'failed') {
    return { label: 'Failed', tone: 'critical' };
  }
  const label = verdict ?? 'UNKNOWN';
  return { label, tone: toneFor(label) };
}
