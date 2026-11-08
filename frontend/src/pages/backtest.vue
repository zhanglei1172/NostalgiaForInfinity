<script setup lang="ts">
const bots = useBotStore();
</script>
<template>
  <BacktestWorkspace
    v-if="bots.activeBot.canRunBacktest && !bots.activeBot.botState.nfi_live_management"
  />
  <ResearchBacktest v-else />
</template>
