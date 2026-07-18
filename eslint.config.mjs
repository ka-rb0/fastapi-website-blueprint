// ESLint flat config for the vanilla-JS frontend (src/app/static/js) plus
// root-level ESM like this config file itself.
//
// Deliberately import-free: the devcontainer images run eslint from a fixed
// prefix outside /workspace (see docker_files/02_dev/Dockerfile), where an
// import like @eslint/js would not resolve. Instead the correctness rules we
// care about are listed explicitly. Run with:  eslint .  (on PATH in the
// devcontainer; `npm ci && npx eslint .` in CI - versions come from
// package-lock.json either way).

// One rule set for every block below, so frontend code and root scripts are
// held to the same standard.
const rules = {
  // correctness
  "no-undef": "error",
  "no-unused-vars": "error",
  "no-redeclare": "error",
  "no-shadow": "error",
  "no-use-before-define": ["error", { functions: false }],
  "no-unreachable": "error",
  "no-dupe-keys": "error",
  "no-dupe-args": "error",
  "no-duplicate-case": "error",
  "no-unsafe-negation": "error",
  "no-self-assign": "error",
  "no-self-compare": "error",
  "no-cond-assign": "error",
  "no-constant-condition": "error",
  "no-constant-binary-expression": "error",
  "no-fallthrough": "error",
  "no-sparse-arrays": "error",
  "no-template-curly-in-string": "error",
  "valid-typeof": "error",
  "use-isnan": "error",
  "array-callback-return": "error",
  "no-promise-executor-return": "error",
  "require-atomic-updates": "error",
  eqeqeq: "error",
  // an empty catch must carry a comment saying why it's fine
  "no-empty": "error",
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
    rules,
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
    rules,
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
