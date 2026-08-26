import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      // The .astro components are markup with inline browser
      // scripts, which this runner cannot import; api.ts is the
      // logic worth measuring.
      include: ['src/lib/**/*.ts'],
      exclude: ['src/**/*.test.ts'],
      all: true,
      reporter: ['text'],
      thresholds: { lines: 80, functions: 80 },
    },
  },
});
