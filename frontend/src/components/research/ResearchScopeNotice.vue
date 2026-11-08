<script setup lang="ts">
import { tr } from '@/i18n';
const bots = useBotStore();
</script>
<template>
  <UAlert
    v-if="bots.activeBot?.botState.nfi_live_management"
    color="info"
    class="mb-6"
    :title="
      tr(
        'Research uses the saved paper recipe and research strategy code. It does not change or start live trading.',
      )
    "
    :description="
      tr(
        'The live recipe and saved strategy copy can differ. Compare them on Recipe settings before using research results for live trading. Research jobs and results are shared with the paper workspace.',
      )
    "
  />
</template>
