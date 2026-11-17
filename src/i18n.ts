/**
 * Minimal, dependency-free i18n for the QAM UI (selection B, Step 1).
 *
 * Why a self-contained t() instead of Decky's LocalizationManager: the device
 * has another plugin using i18n/zh.json + steam_language_map.json, but that
 * machinery is not a documented @decky/api surface on the LOCKED versions and
 * we must not couple to a third-party plugin's format. We ship our own two
 * dictionaries (en.json / zh-CN.json) inlined into the bundle by rollup (the
 * @decky/rollup 1.0.2 toolchain already carries @rollup/plugin-json, so JSON
 * imports work with NO new dependency / lockfile change).
 *
 * Language is chosen from navigator.language (schinese/zh-CN/zh-Hans → zh-CN).
 * Lookup chain: zh-CN → en → fallback → key. Nothing is ever hard-coded in a
 * component; every UI string goes through t(). A missing key degrades to the
 * English text or the key itself, never "undefined".
 */
import en from "./i18n/en.json";
import zhCN from "./i18n/zh-CN.json";

type Dict = Record<string, string>;

const EN: Dict = en as Dict;
const ZH: Dict = zhCN as Dict;

function isChinese(): boolean {
  let lang = "";
  try {
    lang = (typeof navigator !== "undefined" && navigator.language) || "";
  } catch {
    lang = "";
  }
  const l = lang.toLowerCase();
  return l === "zh" || l.startsWith("zh-cn") || l.startsWith("zh-hans") ||
    l === "schinese" || l.startsWith("zh-sg");
}

/** Format a template with {name} placeholders from a plain string map. */
export function format(template: string, vars?: Record<string, string | number | null | undefined>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_m, k: string) => {
    const v = vars[k];
    return v == null ? "" : String(v);
  });
}

/**
 * Translate `key`. Optional `fallback` is the legacy English literal (used as
 * a 3rd-level fallback so a dictionary gap never shows a raw key). `vars`
 * substitutes {placeholders}. Chain: zh-CN → en → fallback → key.
 */
export function t(key: string, fallback?: string, vars?: Record<string, string | number | null | undefined>): string {
  const primary: Dict = isChinese() ? ZH : EN;
  const secondary: Dict = isChinese() ? EN : ZH;
  let raw = primary[key];
  if (raw === undefined) raw = secondary[key];
  if (raw === undefined) raw = fallback !== undefined ? fallback : key;
  return format(raw, vars);
}

/** Translate an error envelope's message by code, keeping the raw code for the small-text line. */
export function errorText(code: string | null, englishMessage: string): string {
  const k = code ? `ERR_${code}` : "";
  return t(k, englishMessage);
}

/** Translate a backend error category (e.g. "safety") through a stable CAT_<UPPER> key. */
export function categoryText(category: string): string {
  const k = `CAT_${String(category || "").toUpperCase()}`;
  return t(k, category || "");
}
