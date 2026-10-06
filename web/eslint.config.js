// Flat config. Lints the TypeScript helpers and the Astro
// components; the build output and dependencies are left alone.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import astro from 'eslint-plugin-astro';

export default [
  { ignores: ['dist/**', '.astro/**', 'node_modules/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...astro.configs.recommended,
  {
    rules: {
      // `x == null` deliberately matches both null and undefined,
      // which is what this code means everywhere it appears.
      // Rewriting those to === would change behaviour.
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-var': 'error',
      'prefer-const': 'error',
    },
  },
  {
    // The inline scripts in .astro components run in the browser
    // and are written in plain ES5-compatible JavaScript on
    // purpose, so `var` is expected there. The plugin extracts each
    // script block into its own virtual file, which is what the
    // second pattern matches.
    files: ['**/*.astro', '**/*.astro/*.js', '**/*.astro/*.ts'],
    rules: {
      'no-var': 'off',
      'prefer-const': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
];
