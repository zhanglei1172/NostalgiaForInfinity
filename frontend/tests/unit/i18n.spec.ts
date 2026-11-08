import { computed, defineComponent, h } from 'vue';
import { mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('Chinese interface language', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });
  afterEach(() => vi.restoreAllMocks());

  it('defaults to Chinese and restores an explicit English preference', async () => {
    let i18n = await import('@/i18n');
    expect(i18n.language.value).toBe('zh-CN');
    expect(i18n.tr('Trade')).toBe('交易');
    i18n.setLanguage('en');
    vi.resetModules();
    i18n = await import('@/i18n');
    expect(i18n.language.value).toBe('en');
    expect(i18n.tr('Trade')).toBe('Trade');
  });

  it('updates computed labels, persists the choice, and rejects unsupported languages', async () => {
    const { tr, setLanguage, language, languageStorageKey } = await import('@/i18n');
    const label = computed(() => tr('Stop Bot'));
    expect(label.value).toBe('停止机器人');
    setLanguage('en');
    expect(label.value).toBe('Stop Bot');
    expect(document.documentElement.lang).toBe('en');
    expect(localStorage.getItem(languageStorageKey)).toBe('en');
    setLanguage('unsupported');
    expect(language.value).toBe('en');
  });

  it('keeps API symbols, prices and missing translations verbatim', async () => {
    const { tr } = await import('@/i18n');
    expect(tr('BTC/USDT')).toBe('BTC/USDT');
    expect(tr(undefined)).toBe('');
    expect(tr('limit')).toBe('limit');
    expect(tr('A new upstream message')).toBe('A new upstream message');
    expect(tr('Really exit trade {0} (Pair {1})?', { 0: 123, 1: 'BTC/USDT' })).toBe(
      '确定退出交易 123（BTC/USDT）吗？',
    );
    expect(tr('Price {price}', { price: '0.00001234' })).toBe('Price 0.00001234');
    expect(tr('Price {price}')).toBe('Price {price}');
  });

  it('renders interpolated server text as text, never as HTML', async () => {
    const { tr } = await import('@/i18n');
    const payload = '<img src=x onerror=alert(1)>';
    const view = mount(
      defineComponent({
        render: () => h('p', tr('Backtest failed: {0}.', { 0: payload })),
      }),
    );
    expect(view.find('img').exists()).toBe(false);
    expect(view.text()).toContain(payload);
    view.unmount();
  });

  it('remains usable when browser storage is blocked', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const { language, tr, setLanguage } = await import('@/i18n');
    expect(language.value).toBe('zh-CN');
    expect(() => setLanguage('en')).not.toThrow();
    expect(tr('Trade')).toBe('Trade');
  });
});
