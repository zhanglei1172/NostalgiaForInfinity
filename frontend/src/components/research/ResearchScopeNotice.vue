<script setup lang="ts">
import { tr } from '@/i18n';
const bots = useBotStore();
const research = useResearchStore();
</script>
<template>
  <UAlert
    v-if="bots.activeBot?.botState.nfi_live_management"
    color="info"
    class="mb-6"
    :title="
      research.info?.scope === 'instance'
        ? tr(
            'This research service belongs to the selected bot. It uses its applied recipe, trading mode and leverage with a fixed research universe.',
          )
        : tr(
            'Research uses the saved paper recipe and research strategy code. It does not change or start live trading.',
          )
    "
    :description="
      research.info?.scope === 'instance'
        ? tr(
            'Research does not change or start live trading. Review the selected bot, dates, fees and available market data before comparing results.',
          )
        : tr(
            'The live recipe and saved strategy copy can differ. Compare them on Recipe settings before using research results for live trading. Research jobs and results are shared with the paper workspace.',
          )
    "
  />
</template>
