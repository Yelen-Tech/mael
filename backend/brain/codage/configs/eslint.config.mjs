// Configuration embarquee de MAEL pour eslint (couche 5). Regles de BASE
// d'eslint seulement : aucun greffon a installer. Les regles de securite qui
// comptent pour le vote croise : no-eval, no-implied-eval, no-new-func,
// no-script-url.
export default [
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: { ecmaVersion: "latest", sourceType: "module" },
    rules: {
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "no-const-assign": "error",
      "no-dupe-keys": "error",
      "no-func-assign": "error",
      "no-redeclare": "error",
      "no-unsafe-finally": "error",
      "no-unsafe-negation": "error",
      "valid-typeof": "error",
      "no-unreachable": "warn",
      "no-self-assign": "warn",
      "eqeqeq": "warn",
    },
  },
];
