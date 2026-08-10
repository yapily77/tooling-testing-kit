// eslint.config.ts
//
// ESLint flat configuration mirroring the quality constraints enforced by `clean_py`:
// - Ruff-style: no-explicit-any, unused vars, import ordering
// - MyPy strict: type-checked rules (unsafe assignment, unsafe member access)
// - Cyclomatic complexity < 6
// - Style: explicit function return types

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import importPlugin from "eslint-plugin-import";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    files: ["**/*.ts", "**/*.tsx"],
    languageOptions: {
      parserOptions: {
        project: true,
      },
    },
    plugins: {
      import: importPlugin,
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": "error",
      "import/order": [
        "error",
        {
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
      complexity: ["error", 5],
      "@typescript-eslint/explicit-function-return-type": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/no-unsafe-call": "error",
    },
  },
);
