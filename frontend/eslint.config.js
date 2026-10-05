import globals from 'globals';
import react from 'eslint-plugin-react';
import hooks from 'eslint-plugin-react-hooks';

export default [{
  files: ['src/**/*.{js,jsx}'],
  plugins: { react, 'react-hooks': hooks },
  linterOptions: { reportUnusedDisableDirectives: false },
  languageOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    parserOptions: { ecmaFeatures: { jsx: true } },
    globals: { ...globals.browser, ...globals.node },
  },
  rules: { 'no-undef': 'error', 'react/jsx-no-undef': 'error' },
}];