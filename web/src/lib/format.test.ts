/*
 * The list page turns raw fields into what a user reads: a size, a
 * time, and one chip that says where an assessment stands. Those
 * decisions live here so they are made once and can be checked.
 */

import { describe, expect, it } from 'vitest';

import {
  failureNote,
  formatClock,
  formatSize,
  formatWhen,
  statusChip,
} from './format';

describe('formatSize', () => {
  it('picks the unit that keeps the number short', () => {
    expect(formatSize(512)).toBe('512 B');
    expect(formatSize(15_167)).toBe('15 KB');
    expect(formatSize(168_500_000)).toBe('160.7 MB');
    expect(formatSize(3_221_225_472)).toBe('3.0 GB');
  });
});

describe('formatWhen', () => {
  it('renders a readable date and time', () => {
    expect(
      formatWhen('2026-09-03T16:44:50+00:00', 'en-GB', 'UTC'),
    ).toBe('3 Sept 2026, 16:44');
  });

  it('is empty for a missing time', () => {
    expect(formatWhen(null, 'en-GB', 'UTC')).toBe('');
  });
});

describe('formatClock', () => {
  it('shows a time without a zone as written', () => {
    expect(formatClock('2026-09-03T16:44:50', 'en-GB')).toBe(
      '3 Sept 2026, 16:44',
    );
  });

  it('is empty for a missing time', () => {
    expect(formatClock(null, 'en-GB')).toBe('');
  });
});

describe('statusChip', () => {
  it('says the assessment is still running', () => {
    expect(statusChip('analyzing', null)).toEqual({
      label: 'Assessing…',
      tone: 'info',
    });
    expect(statusChip('queued', null).label).toBe('Assessing…');
  });

  it('says when it failed', () => {
    expect(statusChip('failed', null)).toEqual({
      label: 'Failed',
      tone: 'critical',
    });
  });

  it('shows the verdict once done', () => {
    expect(statusChip('done', 'WARNING')).toEqual({
      label: 'WARNING',
      tone: 'warning',
    });
    expect(statusChip('done', 'HEALTHY').tone).toBe('healthy');
    expect(statusChip('done', 'CRITICAL').tone).toBe('critical');
  });

  it('falls back to UNKNOWN without a verdict', () => {
    expect(statusChip('done', null)).toEqual({
      label: 'UNKNOWN',
      tone: 'unknown',
    });
    expect(statusChip(null, null).label).toBe('UNKNOWN');
  });

  it('trusts a verdict even without a job record', () => {
    expect(statusChip(null, 'HEALTHY')).toEqual({
      label: 'HEALTHY',
      tone: 'healthy',
    });
  });
});

describe('failureNote', () => {
  it('says why a failed assessment failed', () => {
    expect(failureNote('failed', 'File is not a zip file')).toBe(
      'This assessment failed: File is not a zip file',
    );
  });

  it('still says that it failed without a reason', () => {
    expect(failureNote('failed', null)).toBe('This assessment failed.');
  });

  it('says nothing about a running or finished assessment', () => {
    expect(failureNote('analyzing', null)).toBeNull();
    expect(failureNote('done', null)).toBeNull();
    expect(failureNote(null, null)).toBeNull();
  });
});
