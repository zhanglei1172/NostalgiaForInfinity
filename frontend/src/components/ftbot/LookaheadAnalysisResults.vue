<script setup lang="ts">
import { tr } from '@/i18n';
import type { LookaheadResult } from '@/types';

const props = defineProps<{
  result: LookaheadResult;
}>();

const tableColumns = [
  { accessorKey: 'strategy', header: tr('Strategy'), meta: { class: { td: 'font-mono' } } },
  { accessorKey: 'has_bias', header: tr('Has bias') },
  { accessorKey: 'total_signals', header: tr('Total signals') },
  { accessorKey: 'biased_entry_signals', header: tr('Biased entry signals') },
  { accessorKey: 'biased_exit_signals', header: tr('Biased exit signals') },
  { accessorKey: 'biased_indicators', header: tr('Biased indicators') },
];

const tableData = computed(() => [
  {
    strategy: props.result.strategy,
    has_bias: props.result.has_bias,
    total_signals: props.result.total_signals,
    biased_entry_signals: props.result.biased_entry_signals,
    biased_exit_signals: props.result.biased_exit_signals,
    biased_indicators: props.result.biased_indicators ?? [],
  },
]);
</script>

<template>
  <div class="flex flex-col gap-3">
    <UAlert
      v-if="!result.has_bias"
      color="success"
      class="py-2"
      icon="i-mdi-check-circle"
      :title="tr('No lookahead bias detected')"
      :description="tr('The strategy produced consistent signals across the analyzed timeranges.')"
    />
    <UAlert
      v-else
      color="error"
      class="py-2"
      icon="i-mdi-alert"
      :title="tr('Lookahead bias detected')"
      :description="
        tr(
          'The strategy produced different signals depending on the available data. Backtest results for this strategy are likely unreliable.',
        )
      "
    />

    <div>
      <UTable :data="tableData" :columns="tableColumns">
        <template #has_bias-cell="{ row }">
          <UBadge :color="row.original.has_bias ? 'error' : 'success'" variant="subtle">
            {{ row.original.has_bias ? tr('Yes') : tr('No') }}
          </UBadge>
        </template>
        <template #biased_indicators-cell="{ row }">
          <div v-if="row.original.biased_indicators.length > 0" class="flex flex-wrap gap-1">
            <UBadge
              v-for="ind in row.original.biased_indicators"
              :key="ind"
              color="warning"
              variant="subtle"
            >
              {{ ind }}
            </UBadge>
          </div>
          <span v-else class="text-neutral-500">-</span>
        </template>
      </UTable>
    </div>
  </div>
</template>
