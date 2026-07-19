// ESLint flat config for the vanilla-JS frontend (src/app/static/js) plus
// any Node-side JS in the repo (this config file, future scripts).
//
// Run with:  eslint .  (on PATH in the devcontainer; `npm ci && npx eslint .`
// in CI - versions come from package-lock.json either way).
import { createRequire } from "node:module";

// createRequire honors NODE_PATH, which the dev image points at its baked-in
// npm tools. In a normal clone or CI it resolves the same locked package from
// the workspace's node_modules directory.
const require = createRequire(import.meta.url);
const js = require("@eslint/js");
const globals = require("globals");
const { defineConfig } = require("eslint/config");

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

export default defineConfig([
  // node_modules is ignored by default; the venv `uv sync` creates is not
  { ignores: [".venv/"] },
  {
    // .mjs anywhere (this config file, future scripts) - Node context, no
    // browser globals
    files: ["**/*.mjs"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.nodeBuiltin,
    },
    rules: { ...js.configs.recommended.rules, ...stricterRules },
  },
  {
    // .js/.cjs outside the frontend dir: Node CommonJS (package.json has no
    // "type": "module"). Without this block such files would match nothing
    // and be silently skipped by flat config.
    files: ["**/*.js", "**/*.cjs"],
    ignores: ["src/app/static/js/**"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "commonjs",
      globals: globals.node,
    },
    rules: { ...js.configs.recommended.rules, ...stricterRules },
  },
  {
    files: ["src/app/static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.browser,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...stricterRules,
      // window properties globals.browser declares that would otherwise
      // absorb typos silently instead of failing no-undef
      "no-restricted-globals": [
        "error",
        "event",
        "name",
        "status",
        "length",
        "top",
      ],
    },
  },
  {
    // theme-init.js is loaded as a classic blocking script, not a module
    // (see the <script> tags in templates/base.html) - lint it as one, so
    // module-only
    // syntax like `import` can't pass the linter and then throw in the
    // browser. Globals and rules still come from the block above; this only
    // overrides how the file is parsed.
    files: ["src/app/static/js/theme-init.js"],
    languageOptions: {
      sourceType: "script",
    },
  },
]);
