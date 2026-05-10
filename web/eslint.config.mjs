import nextConfig from "eslint-config-next";
import i18nPlugin from "./eslint/i18n-plugin.mjs";

const config = [
  ...nextConfig,
  {
    rules: {
      // Next 16 includes React Compiler migration diagnostics in the default
      // lint set. This app has not opted into React Compiler yet, so keep the
      // contribution check focused on standard React correctness rules.
      "react-hooks/immutability": "off",
      "react-hooks/preserve-manual-memoization": "off",
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/set-state-in-render": "off",
    },
  },
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}"],
    plugins: {
      i18n: i18nPlugin,
    },
    rules: {
      // During migration keep as warning; change to "error" once phase2/3 complete.
      "i18n/no-literal-ui-text": "warn",
    },
  },
  {
    ignores: ["node_modules/**", ".next/**", "out/**", "dist/**"],
  },
];

export default config;
