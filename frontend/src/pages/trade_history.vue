<script setup lang="ts">
const botStore = useBotStore();
</script>
<template>
  <div class="workspace-panel">
    <div class="hidden md:block">
      <TradeList :trades="botStore.activeBot.closedTrades" show-filter />
    </div>
    <div class="md:hidden p-3"><MobileTradesList history /></div>
  </div>
</template>
