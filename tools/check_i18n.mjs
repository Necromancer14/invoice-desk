#!/usr/bin/env node
// Fails when a translation key used in the portal has no Arabic entry.
//
//   node tools/check_i18n.mjs          check, exit 1 on problems
//   node tools/check_i18n.mjs --keys   also print every key found (handy when adding translations)
//
// Keys are the string literals passed to t("...") or tk("...") in web/src. The checks:
//   * every key has an entry in web/src/locales/ar.json
//   * a key whose English entry has plural forms has Arabic plural forms (an object with "other")
//   * every {placeholder} in a key also appears in its Arabic text
//   * t() is never called with a template literal, which this script could not read
// Arabic entries no key uses are listed as a warning only.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "web", "src");
const ar = JSON.parse(readFileSync(join(src, "locales", "ar.json"), "utf8"));
const en = JSON.parse(readFileSync(join(src, "locales", "en.json"), "utf8"));

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* files(p);
    else if (/\.(ts|tsx)$/.test(name)) yield p;
  }
}

const CALL = /(?<![\w.$])(t|tk)\(\s*(?:"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|(`))/g;
const keys = new Map(); // key -> first place it is used
const problems = [];
for (const file of files(src)) {
  const text = readFileSync(file, "utf8");
  for (const m of text.matchAll(CALL)) {
    const line = text.slice(0, m.index).split("\n").length;
    const where = `${relative(root, file)}:${line}`;
    if (m[4]) { problems.push(`${where}  ${m[1]}() called with a template literal; use a plain string and {placeholders}`); continue; }
    const key = m[2] !== undefined ? JSON.parse(`"${m[2]}"`) : m[3].replace(/\\'/g, "'");
    if (!keys.has(key)) keys.set(key, where);
  }
  // t(cond ? "a" : "b") hides both keys from this script; write cond ? t("a") : t("b") instead
  for (const m of text.matchAll(/(?<![\w.$])t\(\s*[^"'`)\s][^()]*\?\s*["'`]/g)) {
    problems.push(`${relative(root, file)}:${text.slice(0, m.index).split("\n").length}  t() with a conditional string argument; write cond ? t("a") : t("b")`);
  }
}

const holders = (s) => new Set([...s.matchAll(/\{(\w+)\}/g)].map((x) => x[1]));
for (const [key, where] of keys) {
  const entry = ar[key];
  if (entry === undefined) { problems.push(`${where}  no Arabic for: ${JSON.stringify(key)}`); continue; }
  const plural = typeof en[key] === "object";
  if (plural && (typeof entry !== "object" || !entry.other)) problems.push(`${where}  needs Arabic plural forms (zero/one/two/few/many/other): ${JSON.stringify(key)}`);
  for (const text of typeof entry === "object" ? Object.values(entry) : [entry]) {
    for (const h of holders(key)) {
      // a plural form may spell the number out ("فشل فحص واحد"), so {n} is optional there
      if (!text.includes(`{${h}}`) && !(typeof entry === "object" && h === "n")) problems.push(`${where}  Arabic text lacks {${h}}: ${JSON.stringify(key)}`);
    }
  }
}

const unused = Object.keys(ar).filter((k) => !keys.has(k));
if (process.argv.includes("--keys")) for (const k of [...keys.keys()].sort()) console.log(k);
if (unused.length) console.warn(`warning: ${unused.length} Arabic entries are not used: ${unused.map((k) => JSON.stringify(k)).join(", ")}`);
if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`\n${problems.length} problem(s) in ${keys.size} translation keys`);
  process.exit(1);
}
console.log(`ok: ${keys.size} translation keys, all have Arabic`);
