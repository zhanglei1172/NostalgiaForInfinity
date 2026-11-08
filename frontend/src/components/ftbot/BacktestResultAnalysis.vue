<script setup lang="ts">
import { tr } from '@/i18n';
import type { StrategyBacktestResult } from '@/types';

const props = defineProps<{
  backtestResult: StrategyBacktestResult;
}>();
const bots = useBotStore();

const backtestResultStats = computed(() => {
  const tmp = generateBacktestMetricRows(props.backtestResult);
  return formatObjectForTable({ value: tmp }, 'metric');
});

const backtestResultSettings = computed(() => {
  // Transpose Result into readable format
  const tmp = generateBacktestSettingRows(props.backtestResult);

  return formatObjectForTable({ value: tmp }, 'setting');
});
</script>

<template>
  <div class="px-0 w-full">
    <BacktestRiskReport
      :result="backtestResult"
      :filename="bots.activeBot.selectedBacktestMetadata?.filename"
    />
    <div class="flex justify-center">
      <h3 class="font-bold text-2xl mb-2">
        {{ tr('Backtest-result for') }} {{ backtestResult.strategy_name }}
      </h3>
    </div>

    <div class="flex flex-col text-start ms-0 me-2 gap-2">
      <div class="flex flex-col xl:flex-row">
        <div class="px-0 px-xl-0 pe-xl-1 grow">
          <DraggableContainer :header="tr('Strategy settings')">
            <UTable
              :data="backtestResultSettings"
              :columns="[
                { accessorKey: 'setting', header: tr('Setting') },
                { accessorKey: 'value', header: tr('Value') },
              ]"
            />
          </DraggableContainer>
        </div>
        <div class="px-0 xl:px-0 pt-2 xl:pt-0 xl:ps-1 grow">
          <DraggableContainer :header="tr('Metrics')">
            <UTable
              :data="backtestResultStats"
              :columns="[
                { accessorKey: 'metric', header: tr('Metric') },
                { accessorKey: 'value', header: tr('Value') },
              ]"
            />
          </DraggableContainer>
        </div>
      </div>
      <BacktestResultTablePer
        :title="tr('Results per Enter tag')"
        :results="backtestResult.results_per_enter_tag"
        :stake-currency="backtestResult.stake_currency"
        key-header="Enter Tag"
        :stake-currency-decimals="backtestResult.stake_currency_decimals"
      />

      <BacktestResultTablePer
        :title="tr('Results per Exit reason')"
        :results="backtestResult.exit_reason_summary ?? []"
        :stake-currency="backtestResult.stake_currency"
        key-header="Exit Reason"
        :stake-currency-decimals="backtestResult.stake_currency_decimals"
      />

      <BacktestResultTablePer
        v-if="backtestResult.mix_tag_stats"
        :title="tr('Results Mixed Tag')"
        :results="backtestResult.mix_tag_stats ?? []"
        :stake-currency="backtestResult.stake_currency"
        :key-headers="['Enter Tag', 'Exit Tag']"
        :stake-currency-decimals="backtestResult.stake_currency_decimals"
      />

      <BacktestResultTablePer
        :title="tr('Results per pair')"
        :results="backtestResult.results_per_pair"
        :stake-currency="backtestResult.stake_currency"
        key-header="Pair"
        :stake-currency-decimals="backtestResult.stake_currency_decimals"
      />
      <DraggableContainer
        v-if="backtestResult.periodic_breakdown"
        :header="tr('Periodic breakdown')"
      >
        <BacktestResultPeriodBreakdown :periodic-breakdown="backtestResult.periodic_breakdown">
        </BacktestResultPeriodBreakdown>
      </DraggableContainer>

      <DraggableContainer :header="tr('Single trades')">
        <TradeList
          :trades="backtestResult.trades"
          :show-filter="true"
          :stake-currency="backtestResult.stake_currency"
        />
      </DraggableContainer>
    </div>
  </div>
</template>
