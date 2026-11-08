<script setup lang="ts">
import { tr } from '@/i18n';
import type { TabsItem } from '@nuxt/ui';
const botStore = useBotStore();
const activeTab = ref('pairs');
function refreshOHLCV(pair: string, columns: string[]) {
  botStore.activeBot.getPairCandles({ pair, timeframe: botStore.activeBot.timeframe, columns });
}
const tradingTabItems = computed<TabsItem[]>(() => {
  const showText = true;
  return [
    {
      slot: 'pairs',
      value: 'pairs',
      label: showText ? tr('Pairs combined') : undefined,
      icon: 'i-mdi-view-list',
    },
    {
      slot: 'general',
      value: 'general',
      label: showText ? tr('General') : undefined,
      icon: 'i-mdi-information',
    },
    {
      slot: 'performance',
      value: 'performance',
      label: showText ? tr('Performance') : undefined,
      icon: 'i-mdi-chart-line',
    },
    {
      slot: 'balance',
      value: 'balance',
      label: showText ? tr('Balance') : undefined,
      icon: 'i-mdi-bank',
    },
    {
      slot: 'time-breakdown',
      value: 'time-breakdown',
      label: showText ? tr('Time Breakdown') : undefined,
      icon: 'i-mdi-folder-clock',
    },
    {
      slot: 'pairlist',
      value: 'pairlist',
      label: showText ? tr('Pairlist') : undefined,
      icon: 'i-mdi-format-list-group',
    },
    {
      slot: 'pair-locks',
      value: 'pair-locks',
      label: showText ? tr('Pair Locks') : undefined,
      icon: 'i-mdi-lock-alert',
    },
  ];
});
</script>
<template>
  <div class="workspace-page trading-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ tr('STRATEGY CONTROL') }}</p>
        <h1>{{ tr('Trading workspace') }}</h1>
        <p>
          {{ botStore.activeBot.botState.strategy }} · {{ botStore.activeBot.timeframe }} ·
          {{ botStore.activeBot.botState.exchange }}
        </p>
      </div>
      <span class="mode-badge flex items-center gap-2"
        ><span class="status-dot" :class="{ offline: !botStore.activeBot.isBotOnline }" />{{
          botStore.activeBot.botState.state === 'running' ? tr('Running') : tr('Stopped')
        }}
        · {{ botStore.activeBot.openTradeCount }} {{ tr('Open trades') }}</span
      >
    </div>
    <section class="workspace-panel trading-controls">
      <div>
        <h2 class="section-title">{{ tr('Bot controls') }}</h2>
        <p class="muted text-xs mt-2">
          {{
            tr(
              'Pause entries to keep managing existing positions. Stop suspends the entire trading loop.',
            )
          }}
        </p>
      </div>
      <BotControls />
    </section>
    <section class="workspace-panel mb-6">
      <div class="panel-heading flex justify-between items-center">
        <h2>{{ tr('Open Trades') }}</h2>
        <span class="count-badge">{{ botStore.activeBot.openTradeCount }}</span>
      </div>
      <div class="trade-list-area">
        <TradeList
          class="open-trades"
          :trades="botStore.activeBot.openTrades"
          :title="tr('Open trades')"
          :active-trades="true"
          :empty-text="tr('Currently no open trades.')"
        />
      </div>
    </section>
    <section
      v-if="botStore.activeBot.detailTradeId && botStore.activeBot.tradeDetail"
      class="workspace-panel mb-6"
    >
      <div class="panel-heading flex justify-between items-center">
        <h2>{{ tr('Trade Detail') }}</h2>
        <UButton
          icon="i-mdi-close"
          variant="ghost"
          color="neutral"
          :aria-label="tr('Close trade details')"
          @click="botStore.activeBot.setDetailTrade(null)"
        />
      </div>
      <TradeDetail
        :trade="botStore.activeBot.tradeDetail"
        :stake-currency="botStore.activeBot.stakeCurrency"
      />
    </section>
    <section class="workspace-panel mb-6 market-chart">
      <div class="panel-heading">{{ tr('Chart') }}</div>
      <div class="market-chart-body">
        <CandleChartContainer
          :available-pairs="botStore.activeBot.whitelist"
          :historic-view="false"
          :timeframe="botStore.activeBot.timeframe"
          :trades="botStore.activeBot.allTrades"
          @refresh-data="refreshOHLCV"
        />
      </div>
    </section>
    <section class="workspace-panel mb-6">
      <div class="panel-heading">{{ tr('Closed Trades') }}</div>
      <div class="trade-list-area">
        <TradeList
          class="trade-history"
          :trades="botStore.activeBot.closedTrades"
          :title="tr('Trade history')"
          :show-filter="true"
          :empty-text="tr('No closed trades so far.')"
        />
      </div>
    </section>
    <section class="workspace-panel">
      <div class="panel-heading">{{ tr('Strategy & account') }}</div>
      <UTabs
        v-model="activeTab"
        color="primary"
        :items="tradingTabItems"
        variant="link"
        :ui="{
          list: 'overflow-x-auto justify-start',
          trigger: 'shrink-0 grow-0 px-4 py-4',
          content: 'p-4 overflow-auto',
        }"
      >
        <template #pairs
          ><PairSummary
            :pairlist="botStore.activeBot.whitelist"
            :current-locks="botStore.activeBot.activeLocks"
            :trades="botStore.activeBot.openTrades"
        /></template>
        <template #general><BotStatus /></template
        ><template #performance><BotPerformance /></template
        ><template #balance><BotBalance /></template
        ><template #time-breakdown><PeriodBreakdown /></template
        ><template #pairlist><PairListLive /></template
        ><template #pair-locks><PairLockList /></template>
      </UTabs>
    </section>
  </div>
</template>
<style scoped>
.trading-controls {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
  padding: 22px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.trade-list-area {
  min-height: 180px;
  max-height: 600px;
  overflow: auto;
}
.market-chart-body {
  height: 520px;
  padding: 12px;
}
.count-badge {
  padding: 3px 9px;
  border-radius: 6px;
  background: var(--workspace-elevated);
  font-size: 12px;
}
@media (max-width: 767px) {
  .trading-controls {
    padding: 18px;
  }
  .market-chart-body {
    height: 420px;
    padding: 6px;
  }
}
</style>
