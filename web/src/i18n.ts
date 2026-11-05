/**
 * Translations. Keys are the English text. en.json only holds English plural forms;
 * every other English string is its own key. ar.json must have an entry for every key
 * used in the source: `node tools/check_i18n.mjs` fails the build if one is missing.
 *
 *   t("Approve")                         plain string
 *   t("{n} of {total}", { n, total })     placeholders
 *   t("{n} checks failed", { n })         plural: the entry is { one, two, few, many, other, zero }
 *   tk("Invoice number")                  marks a key kept in a constant and translated later with t(label)
 */
import en from "./locales/en.json";
import ar from "./locales/ar.json";

export type Lang = "en" | "ar";
export type Vars = Record<string, string | number>;
type Plural = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };
type Dict = Record<string, string | Plural>;

const DICTS: Record<Lang, Dict> = { en: en as Dict, ar: ar as Dict };

/** Locale used for numbers and dates. Arabic keeps Latin digits and the Gregorian calendar, as invoices print them. */
export const LOCALE: Record<Lang, string> = { en: "en-GB", ar: "ar-SA-u-nu-latn-ca-gregory" };

/** Marks a string as a translation key without translating it yet. */
export const tk = (s: string) => s;

export function makeT(lang: Lang) {
  const plural = new Intl.PluralRules(LOCALE[lang]);
  const num = new Intl.NumberFormat(LOCALE[lang]);
  return (key: string, vars?: Vars): string => {
    const entry = DICTS[lang][key] ?? DICTS.en[key] ?? key;
    let text: string;
    if (typeof entry === "string") text = entry;
    else {
      const n = Number(vars?.n ?? 0);
      // Arabic uses its "zero" form for 0; Intl.PluralRules reports that as "zero" too.
      text = entry[plural.select(n)] ?? entry.other;
    }
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? (typeof vars[k] === "number" ? num.format(vars[k] as number) : String(vars[k])) : m));
  };
}
