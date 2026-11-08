<script setup lang="ts">
import { tr } from '@/i18n';
import { useResearchStore } from '@/stores/research';
const research = useResearchStore();
const route = useRoute();
const { confirm } = useConfirmBox();
const blocked = computed(() => research.busy || research.running || research.downloading);
onMounted(async () => {
  await research.load();
  if (
    typeof route.query.strategy === 'string' &&
    research.strategies.includes(route.query.strategy)
  )
    research.strategy = route.query.strategy;
});
async function stop() {
  if (
    await confirm({
      title: tr('Stop Backtest'),
      message: tr('Stop the current historical simulation? The paper bot continues running.'),
    })
  )
    await research.stop();
}
const historyOptions = computed(() =>
  research.history.map((entry, index) => ({
    label: `${entry.strategy} · ${new Date(entry.backtest_start_time * 1000).toLocaleString()} · ${entry.filename}`,
    value: index,
  })),
);
const selectedHistory = ref<number>();
watch(selectedHistory, (value) => {
  const entry = value === undefined ? undefined : research.history[value];
  if (entry) void research.selectHistory(entry);
});
</script>
<template>
  <div class="workspace-page research-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ tr('STRATEGY RESEARCH') }}</p>
        <h1>{{ tr('Backtesting') }}</h1>
        <p>
          {{ tr('Test a strategy on historical candles and compare its returns month by month.') }}
        </p>
      </div>
      <UButton to="/strategies" color="neutral" icon="i-mdi-code-braces">{{
        tr('Strategy library')
      }}</UButton>
      <UButton to="/recipes" color="neutral" icon="i-mdi-tune-variant">{{
        tr('Recipe settings')
      }}</UButton>
    </div>
    <ResearchScopeNotice />
    <UAlert v-if="research.error" :title="research.error" color="error" class="mb-6" role="alert" />
    <div v-if="research.loading && !research.info" class="workspace-panel p-6 muted" role="status">
      {{ tr('Loading research workspace…') }}
    </div>
    <div v-else-if="!research.info" class="workspace-panel p-6">
      <p class="muted mb-4">
        {{ tr('The research service is unavailable. Start the backtesting service and retry.') }}
      </p>
      <UButton icon="i-mdi-refresh" @click="research.load">{{ tr('Retry') }}</UButton>
    </div>
    <template v-else>
      <section class="workspace-panel mb-6">
        <div class="panel-heading">
          <h2>{{ tr('Backtesting parameters') }}</h2>
          <p class="muted font-normal text-xs mt-2">
            {{
              tr('Default: the last 3 complete months. Dates use UTC; the end date is exclusive.')
            }}
          </p>
        </div>
        <form class="research-form" @submit.prevent="research.start">
          <UFormField :label="tr('Strategy')" required
            ><USelect
              v-model="research.strategy"
              :items="research.strategies"
              class="w-full"
              :disabled="blocked"
          /></UFormField>
          <UFormField :label="tr('Starting capital:')" required
            ><UInputNumber
              v-model="research.capital"
              :min="100"
              :step="100"
              :increment="false"
              :decrement="false"
              class="w-full"
              :disabled="blocked"
          /></UFormField>
          <UFormField :label="tr('Start date (UTC)')" required
            ><UInput v-model="research.startDate" type="date" class="w-full" :disabled="blocked"
          /></UFormField>
          <UFormField :label="tr('End date (exclusive, UTC)')" required
            ><UInput v-model="research.endDate" type="date" class="w-full" :disabled="blocked"
          /></UFormField>
          <div class="research-scope">
            <p v-if="research.info.recipe_revision !== undefined">
              {{
                tr('Saved recipe revision: {revision}. The next run uses these settings.', {
                  revision: research.info.recipe_revision,
                })
              }}
            </p>
            <p>
              {{ research.info.exchange }} · {{ tr('Spot') }} · 5m ·
              {{ research.info.stake_currency }}
            </p>
            <p>{{ tr('Tested pairs') }}: {{ research.info.pairs.join(', ') }}</p>
            <p>
              {{ tr('Fee per side') }}: {{ formatPercent(research.info.fee, 2) }} ·
              {{ tr('Max open trades:') }} {{ research.info.max_open_trades }}
            </p>
            <BaseCheckbox v-model="research.protections" :disabled="blocked" class="mt-3">{{
              tr('Enable Protections:')
            }}</BaseCheckbox>
          </div>
          <p v-if="!research.validRange" class="text-error text-sm col-span-full">
            {{ tr('Choose a valid completed date range of no more than three years.') }}
          </p>
          <div class="research-actions">
            <UButton
              type="button"
              color="neutral"
              icon="i-mdi-cloud-download-outline"
              :disabled="blocked || !research.validRange"
              @click="research.prepare"
              >{{ tr('1. Download historical data') }}</UButton
            ><UButton
              type="submit"
              icon="i-mdi-play"
              variant="solid"
              :disabled="
                blocked || !research.validRange || !research.strategy || research.capital <= 0
              "
              >{{ tr('2. Start backtest') }}</UButton
            ><UButton
              v-if="research.running"
              type="button"
              color="error"
              :disabled="research.busy"
              @click="stop"
              >{{ tr('Stop Backtest') }}</UButton
            ><UButton
              type="button"
              color="neutral"
              icon="i-mdi-refresh"
              :disabled="research.busy"
              @click="research.refresh"
              >{{ tr('Refresh') }}</UButton
            >
          </div>
        </form>
        <p class="px-6 pb-6 muted text-xs leading-relaxed">
          {{
            tr(
              'Download candles before the first run or after extending the dates. NFI requires 5m, 15m, 1h, 4h and 1d data; warm-up candles are fetched automatically. Jobs continue if you leave this page.',
            )
          }}
        </p>
      </section>
      <UAlert
        v-if="research.downloading"
        color="info"
        :title="tr('Downloading historical data…')"
        :description="`${research.info.preparation.timeframe ?? '…'} · ${research.info.preparation.completed}/${research.info.preparation.total}`"
        class="mb-6"
        role="status"
      />
      <UAlert
        v-else-if="research.info.preparation.status === 'failed'"
        color="error"
        :title="tr('Historical data download failed. Check connectivity and retry the download.')"
        class="mb-6"
        role="alert"
      />
      <UAlert
        v-else-if="research.info.preparation.status === 'success'"
        color="success"
        :title="tr('Historical data is ready. You can start the backtest.')"
        :description="`${research.info.preparation.start_date} → ${research.info.preparation.end_date} UTC`"
        class="mb-6"
      />
      <section v-if="research.running" class="workspace-panel p-6 mb-6" role="status">
        <div class="flex justify-between mb-4">
          <strong>{{ tr('Backtest running:') }} {{ research.status?.step }}</strong
          ><span>{{ formatPercent(research.status?.progress ?? 0, 1) }}</span>
        </div>
        <UProgress :model-value="(research.status?.progress ?? 0) * 100" />
        <p class="muted text-xs mt-3">
          {{ tr('The paper bot continues running during research.') }}
        </p>
      </section>
      <section class="workspace-panel p-6 mb-6">
        <UFormField :label="tr('Saved backtest results')"
          ><USelectMenu
            v-model="selectedHistory"
            :items="historyOptions"
            value-key="value"
            :placeholder="tr('Choose a saved result')"
            :disabled="research.busy || research.running"
            class="w-full"
        /></UFormField>
        <p v-if="!research.history.length" class="muted text-xs mt-3">
          {{ tr('Completed backtests are saved automatically and survive container restarts.') }}
        </p>
      </section>
      <MonthlyBacktestReport
        v-if="research.result"
        :result="research.result"
        :filename="research.resultFilename"
      />
      <section v-else class="workspace-panel p-10 text-center">
        <UIcon name="i-mdi-chart-bar" class="size-10 muted mb-4" />
        <h2 class="section-title">{{ tr('Monthly results will appear here') }}</h2>
        <p class="muted text-sm mt-3">
          {{ tr('Run a backtest or choose a saved result to see actual historical returns.') }}
        </p>
      </section>
    </template>
  </div>
</template>
<style scoped>
.research-page {
  max-width: 1500px;
}
.research-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
  padding: 24px;
}
.research-scope {
  grid-column: 1/-1;
  background: #7794fa08;
  border: 1px solid var(--workspace-border);
  border-radius: 12px;
  padding: 18px;
  font-size: 13px;
  line-height: 2;
  color: var(--workspace-muted);
}
.research-actions {
  grid-column: 1/-1;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
@media (max-width: 639px) {
  .research-form {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
