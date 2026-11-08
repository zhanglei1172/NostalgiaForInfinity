import { readonly, ref } from 'vue';
import chinese from './zh-CN.json';

export type Language = 'zh-CN' | 'en';
export const languageStorageKey = 'nfi-ui-language';

function initialLanguage(): Language {
  try {
    return localStorage.getItem(languageStorageKey) === 'en' ? 'en' : 'zh-CN';
  } catch {
    return 'zh-CN';
  }
}

const selectedLanguage = ref<Language>(initialLanguage());
export const language = readonly(selectedLanguage);

export function setLanguage(value: unknown): void {
  if (value !== 'zh-CN' && value !== 'en') return;
  selectedLanguage.value = value;
  document.documentElement.lang = value;
  try {
    localStorage.setItem(languageStorageKey, value);
  } catch {
    // The interface remains usable when browser storage is unavailable.
  }
}

/** Translate display text only. API fields, symbols and user input stay verbatim. */
export function tr(
  message: string | null | undefined,
  parameters: Record<string, unknown> = {},
): string {
  if (message == null) return '';
  const key = message.replace(/\s+/g, ' ').trim();
  const translated =
    selectedLanguage.value === 'zh-CN'
      ? ((chinese as Record<string, string>)[key] ?? message)
      : message;
  return translated.replace(/\{(\w+)\}/g, (token, name: string) =>
    Object.hasOwn(parameters, name) ? String(parameters[name]) : token,
  );
}
