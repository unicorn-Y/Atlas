import { messages as enUS } from './locales/en-US';
import { messages as zhCN } from './locales/zh-CN';

export type Locale = 'zh-CN' | 'en-US';
export type LocaleNamespace = string;

const KEY = 'atlas.preference.locale';
const SLOT_PATTERN = /__U26_SLOT_(\d+)__/g;
const namespaceCatalogs = new Map<LocaleNamespace, Partial<Record<Locale, Record<string, string>>>>();

registerLocaleNamespace('updates', 'en-US', {
  '查看说明': 'View details',
  '收起': 'Collapse',
  '跳过这个版本': 'Skip this version',
  '稍后提醒': 'Remind me later',
  '下载并重启安装': 'Download and restart installation',
  '立即更新源码': 'Update source now',
});
registerLocaleNamespace('updates', 'zh-CN', {
  '查看说明': '查看说明',
  '收起': '收起',
  '跳过这个版本': '跳过这个版本',
  '稍后提醒': '稍后提醒',
  '下载并重启安装': '下载并重启安装',
  '立即更新源码': '立即更新源码',
});

export function registerLocaleNamespace(namespace: LocaleNamespace, locale: Locale, messages: Record<string, string>): void {
  const catalogs = namespaceCatalogs.get(namespace) ?? {};
  catalogs[locale] = { ...catalogs[locale], ...messages };
  namespaceCatalogs.set(namespace, catalogs);
}

const englishPatterns = Object.entries(enUS)
  .filter(([source]) => /__U26_SLOT_\d+__/.test(source))
  .map(([source, translated]) => {
    SLOT_PATTERN.lastIndex = 0;
    const slots: number[] = [];
    let expression = '^';
    let cursor = 0;
    for (const match of source.matchAll(SLOT_PATTERN)) {
      const index = match.index ?? 0;
      expression += source.slice(cursor, index).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      expression += '([\\s\\S]*?)';
      slots.push(Number(match[1]));
      cursor = index + match[0].length;
    }
    expression += source.slice(cursor).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$';
    return { regex: new RegExp(expression), slots, translated };
  });


const originals = new WeakMap<Text, { source: string; translated: string }>();
const attributeOriginals = new WeakMap<Element, Map<string, { source: string; translated: string }>>();

function localizeNode(node: Node, locale: Locale): void {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node as Text;
    if (/^(SCRIPT|STYLE|CODE|PRE|TEXTAREA)$/.test(text.parentElement?.tagName ?? '') || text.parentElement?.closest('[data-no-i18n]')) return;
    let saved = originals.get(text);
    const current = text.nodeValue ?? '';
    if (!saved) {
      saved = { source: current, translated: current };
      originals.set(text, saved);
    } else if (current !== saved.translated) {
      // React or another owner replaced the node text since the last locale pass.
      saved.source = current;
    }
    const parts = /^(\s*)([\s\S]*?)(\s*)$/.exec(saved.source);
    if (!parts) return;
    const translated = t(parts[2], locale);
    const value = `${parts[1]}${translated}${parts[3]}`;
    if (text.nodeValue !== value) text.nodeValue = value;
    saved.translated = value;
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const element = node as Element;
  localizeAttributes(element, locale);
  for (const child of Array.from(node.childNodes)) localizeNode(child, locale);
}

function localizeAttributes(element: Element, locale: Locale): void {
  let saved = attributeOriginals.get(element);
  if (!saved) { saved = new Map(); attributeOriginals.set(element, saved); }
  for (const name of ['aria-label', 'title', 'placeholder']) {
    const current = element.getAttribute(name);
    if (current === null) continue;
    let value = saved.get(name);
    if (!value) {
      value = { source: current, translated: current };
      saved.set(name, value);
    } else if (current !== value.translated) {
      value.source = current;
    }
    const translated = t(value.source, locale);
    if (current !== translated) element.setAttribute(name, translated);
    value.translated = translated;
  }
}

export function observeLocalizedCopy(root: HTMLElement, locale: Locale): () => void {
  localizeNode(root, locale);
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes' && record.target.nodeType === Node.ELEMENT_NODE) localizeAttributes(record.target as Element, locale);
      else if (record.type === 'characterData') localizeNode(record.target, locale);
      else for (const added of Array.from(record.addedNodes)) localizeNode(added, locale);
    }
  });
  observer.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['aria-label', 'title', 'placeholder'] });
  return () => observer.disconnect();
}

export function readLocale(): Locale {
  try { return localStorage.getItem(KEY) === 'en-US' || (!localStorage.getItem(KEY) && localStorage.getItem('atlas.preference.u4-appearance')?.includes('"language":"en"')) ? 'en-US' : 'zh-CN'; }
  catch { return 'zh-CN'; }
}

export function saveLocale(locale: Locale): void {
  try { localStorage.setItem(KEY, locale); } catch { /* storage can be unavailable */ }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale;
    document.body.dataset.language = locale;
  }
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('atlas:locale-change', { detail: locale }));
}

export function t(source: string, locale: Locale = readLocale()): string {
  if (locale !== 'en-US') return zhCN[source] ?? source;
  const exact = enUS[source];
  if (exact !== undefined) return exact;
  if (!/[\u3400-\u9fff]/.test(source)) return source;
  for (const pattern of englishPatterns) {
    const match = pattern.regex.exec(source);
    if (!match) continue;
    const values = new Map(pattern.slots.map((slot, index) => [slot, match[index + 1]]));
    return pattern.translated.replace(SLOT_PATTERN, (_token, slot: string) => values.get(Number(slot)) ?? '');
  }
  return source;
}

export function tn(namespace: LocaleNamespace, source: string, locale: Locale = readLocale()): string {
  const scoped = namespaceCatalogs.get(namespace)?.[locale]?.[source];
  return scoped ?? t(source, locale);
}
