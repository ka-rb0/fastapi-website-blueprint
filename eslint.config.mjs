// ESLint flat config for the vanilla-JS frontend (src/app/static/js) plus
// root-level ESM like this config file itself.
//
// Run with:  eslint .  (on PATH in the devcontainer; `npm ci && npx eslint .`
// in CI - versions come from package-lock.json either way).
import { createRequire } from "node:module";

// createRequire honors NODE_PATH, which the dev image points at its baked-in
// npm tools. In a normal clone or CI it resolves the same locked package from
// the workspace's node_modules directory.
const require = createRequire(import.meta.url);
const js = require("@eslint/js");

// One rule set for every block below, so frontend code and root scripts are
// held to the same standard. js.configs.recommended provides the baseline;
// these only add rules that go beyond it.
const stricterRules = {
  // correctness
  "no-shadow": "error",
  "no-use-before-define": ["error", { functions: false }],
  "no-self-compare": "error",
  "no-template-curly-in-string": "error",
  "array-callback-return": "error",
  "no-promise-executor-return": "error",
  "require-atomic-updates": "error",
  eqeqeq: "error",
  // hygiene
  "no-var": "error",
  "prefer-const": "error",
  // console.log is debug residue; warn/error are how real failures surface
  "no-console": ["error", { allow: ["warn", "error"] }],
  "no-implicit-globals": "error",
  "no-eval": "error",
  "no-implied-eval": "error",
};

export default [
  // node_modules is ignored by default; the venv `uv sync` creates is not
  { ignores: [".venv/"] },
  {
    // root-level ESM (this config file, future scripts) - no browser globals
    files: ["*.mjs"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
    },
    rules: { ...js.configs.recommended.rules, ...stricterRules },
  },
  {
    files: ["src/app/static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      // only what the code actually uses - extend as the frontend grows
      globals: {
        document: "readonly",
        localStorage: "readonly",
        fetch: "readonly",
        console: "readonly",
      },
    },
    rules: { ...js.configs.recommended.rules, ...stricterRules },
  },
  {
    // theme-init.js is loaded as a classic blocking script, not a module
    // (see the <script> tags in index.html) - lint it as one, so module-only
    // syntax like `import` can't pass the linter and then throw in the
    // browser. Globals and rules still come from the block above; this only
    // overrides how the file is parsed.
    files: ["src/app/static/js/theme-init.js"],
    languageOptions: {
      sourceType: "script",
    },
  },
];
