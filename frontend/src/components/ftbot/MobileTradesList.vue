<script setup lang="ts">
import { tr } from '@/i18n';
defineProps<{
  history?: boolean;
}>();
const botStore = useBotStore();
</script>

<template>
  <div>
    <!-- <TradeList
      class="open-trades"
      :trades="openTrades"
      title="Open trades"
      :active-trades="true"
      empty-text="Currently no open trades."
    /> -->
    <CustomTradeList
      v-if="!history && !botStore.activeBot.detailTradeId"
      :trades="botStore.activeBot.openTrades"
      :title="tr('Open trades')"
      :active-trades="true"
      :stake-currency-decimals="botStore.activeBot.stakeCurrencyDecimals"
      :empty-text="tr('No open Trades.')"
    />
    <CustomTradeList
      v-if="history && !botStore.activeBot.detailTradeId"
      :trades="botStore.activeBot.closedTrades"
      :title="tr('Trade history')"
      :stake-currency-decimals="botStore.activeBot.stakeCurrencyDecimals"
      :empty-text="tr('No closed trades so far.')"
    />
    <div
      v-if="botStore.activeBot.detailTradeId && botStore.activeBot.tradeDetail"
      class="flex flex-col"
    >
      <UButton
        color="neutral"
        class="self-start my-1 ms-1"
        @click="botStore.activeBot.setDetailTrade(null)"
        :label="tr('Back')"
        icon="mdi:arrow-left"
      />
      <TradeDetail
        :trade="botStore.activeBot.tradeDetail"
        :stake-currency="botStore.activeBot.stakeCurrency"
      />
    </div>
  </div>
</template>
