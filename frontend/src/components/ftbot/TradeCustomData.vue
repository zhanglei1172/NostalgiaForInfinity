<script setup lang="ts">
import { tr } from '@/i18n';
import type { Trade } from '@/types';
export interface TradeCustomDataProps {
  tradeId: Trade['trade_id'];
}
const props = defineProps<TradeCustomDataProps>();

const botStore = useBotStore();
const { state: customData, execute } = useAsyncState(
  () => botStore.activeBot.getCustomDataForTrade(props.tradeId),
  null,
  { immediate: true, resetOnExecute: false, shallow: true },
);
</script>

<template>
  <div>
    <template v-for="x in customData" :key="x.trade_id">
      <template v-for="y in x.custom_data" :key="y.key">
        <ValuePair :description="y.key">{{ y.value }}</ValuePair>
      </template>
      <template v-if="x.custom_data.length === 0">
        <p class="italic text-sm text-neutral-500">{{ tr('No custom data for this trade') }}</p>
      </template>
    </template>

    <UButton @click="execute()" icon="mdi:reload" :label="tr('Reload Custom Data')" class="mt-2" />
  </div>
</template>
