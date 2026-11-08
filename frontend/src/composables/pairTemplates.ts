import { tr } from '@/i18n';
const pairTemplates = ref([
  {
    get description() {
      return tr('All USDT Pairs');
    },
    pairs: ['.*/USDT'],
  },
  {
    get description() {
      return tr('All USDT Futures Pairs');
    },
    pairs: ['.*/USDT:USDT'],
  },
]);

export function usePairTemplates() {
  return {
    pairTemplates: computed(() => pairTemplates.value.map((x, idx) => ({ ...x, idx }))),
  };
}
