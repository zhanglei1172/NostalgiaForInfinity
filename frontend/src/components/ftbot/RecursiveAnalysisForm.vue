<script setup lang="ts">
import { tr } from '@/i18n';
import type { RecursiveAnalysisPayload } from '@/types';

const props = defineProps<{
  running: boolean;
}>();

const emit = defineEmits<{
  start: [payload: RecursiveAnalysisPayload];
}>();

const botStore = useBotStore();
const btStore = useBtStore();

const canStart = computed(
  () => !!btStore.strategy && !props.running && botStore.activeBot.canRunBacktest,
);

function emitStart() {
  const payload: RecursiveAnalysisPayload = {
    strategy: btStore.strategy,
  };
  if (btStore.selectedTimeframe) {
    payload.timeframe = btStore.selectedTimeframe;
  }
  if (btStore.timerange) {
    payload.timerange = btStore.timerange;
  }
  if (btStore.recursiveStartupCandles.length > 0) {
    payload.startup_candle = btStore.recursiveStartupCandles;
  }
  emit('start', payload);
}

onMounted(() => {
  if (botStore.activeBot.strategyList.length === 0) {
    botStore.activeBot.getStrategyList();
  }
});
</script>

<template>
  <div>
    <UAlert
      color="info"
      class="mb-3 py-2"
      :title="tr('Recursive analysis')"
      :description="
        tr(
          'Checks your strategy\'s indicators for recursive formula issues by comparing indicator values calculated with different startup candle counts. Indicators that show a difference are likely affected by the amount of startup data and may produce inconsistent results between backtesting and dry/live runs.',
        )
      "
    />

    <div class="flex flex-col gap-3">
      <div>
        <span class="font-bold">{{ tr('Strategy') }}</span>
        <StrategySelect v-model="btStore.strategy" />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 items-center">
        <label for="recursive-timeframe">{{ tr('Timeframe:') }}</label>
        <TimeframeSelect id="recursive-timeframe" v-model="btStore.selectedTimeframe" />
      </div>

      <div class="border dark:border-neutral-700 border-neutral-300 rounded-sm p-2">
        <div class="flex items-center gap-2">
          <label for="recursive-startup-candles" class="font-bold">{{
            tr('Startup candle counts:')
          }}</label>
          <InfoBox
            :hint="
              tr(
                'Comma separated list of startup candle counts to compare against each other. Leave empty to use the backend defaults.',
              )
            "
          />
        </div>
        <UInput
          id="recursive-startup-candles"
          v-model="btStore.recursiveStartupCandleInput"
          class="w-full mt-1"
          placeholder="e.g. 199,399,499,999,1999"
        />
      </div>

      <TimeRangeSelect
        v-model="btStore.timerange"
        :can-use-time="botStore.activeBot.botFeatures.timerangeWithTime"
        class="mx-auto mt-1"
      />

      <div class="flex justify-center mt-2">
        <UButton
          icon="i-mdi-play"
          variant="solid"
          :loading="running"
          :disabled="!canStart"
          @click="emitStart"
        >
          {{ tr('Start recursive analysis') }}
        </UButton>
      </div>
    </div>
  </div>
</template>
