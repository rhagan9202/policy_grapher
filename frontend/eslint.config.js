import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },
  {
    // Plain JS — this config file itself, chiefly. Without a block matching them,
    // no rule applies to a .js file at all and a typo in here lints clean.
    files: ['**/*.{js,mjs,cjs}'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
  {
    // Vitest injects describe/it/expect, and setup files touch Node globals.
    files: ['**/*.test.{ts,tsx}', 'src/setupTests.ts', '*.config.ts'],
    languageOptions: {
      globals: { ...globals.node, ...globals.vitest },
    },
  },
)
