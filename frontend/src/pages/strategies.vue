<script setup lang="ts">
import { tr } from '@/i18n';
import { useResearchStore } from '@/stores/research';
import type { StrategyResult } from '@/types';
const research = useResearchStore();
const details = ref<StrategyResult>();
const loading = ref(false);
const failed = ref(false);
const showCode = ref(false);
let sequence = 0;
async function loadDetails() {
  const current = ++sequence;
  details.value = undefined;
  failed.value = false;
  showCode.value = false;
  if (!research.strategy) return;
  loading.value = true;
  try {
    const value = await research.getStrategy(research.strategy);
    if (current === sequence) details.value = value;
  } catch {
    if (current === sequence) failed.value = true;
  } finally {
    if (current === sequence) loading.value = false;
  }
}
onMounted(async () => {
  await research.load();
  await loadDetails();
});
watch(() => research.strategy, loadDetails);
onBeforeUnmount(() => {
  ++sequence;
});
</script>
<template>
  <div class="workspace-page strategy-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ tr('STRATEGY RESEARCH') }}</p>
        <h1>{{ tr('Strategy library') }}</h1>
        <p>
          {{ tr('Inspect available strategy code and choose a strategy for historical testing.') }}
        </p>
      </div>
      <UButton to="/backtest" color="neutral" icon="i-mdi-flask-outline">{{
        tr('Backtesting')
      }}</UButton>
    </div>
    <ResearchScopeNotice />
    <UAlert v-if="research.error" :title="research.error" color="error" class="mb-6" role="alert" />
    <section class="workspace-panel p-6 mb-6">
      <div class="flex gap-3 items-end">
        <UFormField :label="tr('Strategy')" class="grow min-w-0"
          ><USelect
            v-model="research.strategy"
            :items="research.strategies"
            class="w-full" /></UFormField
        ><UButton
          color="neutral"
          icon="i-mdi-refresh"
          :loading="research.loading"
          @click="research.load().then(loadDetails)"
          >{{ tr('Refresh') }}</UButton
        >
      </div>
      <p class="muted text-xs mt-4">
        {{
          tr(
            'Choosing a strategy here only changes the research selection. Trading bots keep their current strategies.',
          )
        }}
      </p>
    </section>
    <div v-if="loading" class="workspace-panel p-6 muted" role="status">
      {{ tr('Loading strategy…') }}
    </div>
    <UAlert
      v-else-if="failed"
      color="error"
      :title="tr('The strategy could not be loaded. Refresh and try again.')"
      role="alert"
    />
    <section v-else-if="details" class="workspace-panel p-6">
      <div class="flex justify-between items-start gap-4 flex-wrap">
        <div>
          <h2 class="section-title break-all">{{ details.strategy }}</h2>
          <p class="muted text-sm mt-3">
            {{ tr('Timeframe:') }} {{ details.timeframe }} · {{ tr('Available parameters') }}:
            {{ details.params.length }}
          </p>
        </div>
        <UButton
          :to="{ path: '/backtest', query: { strategy: details.strategy } }"
          icon="i-mdi-play"
          variant="solid"
          >{{ tr('Backtest this strategy') }}</UButton
        >
      </div>
      <StrategyParameters v-if="details.params.length" :strategy="details" class="mt-6" /><UButton
        color="neutral"
        icon="i-mdi-code-braces"
        class="mt-6"
        @click="showCode = !showCode"
        >{{ showCode ? tr('Hide source code') : tr('View source code') }}</UButton
      ><textarea
        v-if="showCode"
        readonly
        :value="details.code"
        :aria-label="tr('Strategy source code')"
        spellcheck="false"
        class="strategy-code"
      />
    </section>
  </div>
</template>
<style scoped>
.strategy-page {
  max-width: 1500px;
}
.strategy-code {
  display: block;
  margin-top: 20px;
  width: 100%;
  height: 560px;
  max-height: 65vh;
  resize: vertical;
  padding: 18px;
  background: var(--workspace-bg);
  border: 1px solid var(--workspace-border);
  border-radius: 10px;
  font-family: monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre;
}
</style>
