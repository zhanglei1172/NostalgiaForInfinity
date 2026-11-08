<script setup lang="ts">
import { tr } from '@/i18n';
const botStore = useBotStore();
</script>
<template>
  <div class="workspace-panel p-5 sm:p-7">
    <p class="muted text-sm mb-6">
      {{ tr('Review available funds and the current valuation of assets managed by this bot.') }}
      {{ botStore.activeBot.stakeCurrency }}
    </p>
    <BotBalance />
  </div>
</template>
