# Adding a language

The panel ships with English (`en`) and German (`de`). Adding another
language is one JSON file + one registration line:

1. Copy `frontend/src/locales/en.json` to `frontend/src/locales/<code>.json`
   (e.g. `fr.json`) and translate the values. Keys must stay identical;
   `{placeholders}` must be kept.
2. Register it in `frontend/src/lib/i18n.js`:

   ```js
   import fr from "../locales/fr.json";
   export const LOCALES = { en, de, fr };
   export const LOCALE_NAMES = { en: "English", de: "Deutsch", fr: "Français" };
   ```

3. `npm run build` — done. The language auto-selects for matching browsers
   and appears in every language chooser.

Missing keys fall back to English at runtime, so partial translations are
safe. Pull requests welcome!
