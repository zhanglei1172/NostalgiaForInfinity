<script setup lang="ts">
import { tr } from '@/i18n';
const botStore = useBotStore();
const scrollContainer = ref<HTMLElement | null>(null);
const query = ref('');
const level = ref('all');
const loading = ref(false);
const failed = ref(false);
const levels = computed(() => [
  { label: tr('All levels'), value: 'all' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'DEBUG', value: 'DEBUG' },
]);
const logs = computed(() =>
  (botStore.activeBot?.lastLogs ?? []).filter(
    (log) =>
      (level.value === 'all' || log[3] === level.value) &&
      log.join(' ').toLowerCase().includes(query.value.toLowerCase()),
  ),
);
async function refreshLogs() {
  loading.value = true;
  failed.value = false;
  try {
    await botStore.activeBot.getLogs();
    await nextTick();
    scrollToBottom();
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}
function scrollToBottom() {
  if (scrollContainer.value) scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight;
}
onMounted(refreshLogs);
</script>
<template>
  <section class="workspace-panel log-viewer">
    <div class="log-toolbar">
      <div class="flex flex-wrap gap-3">
        <UInput
          v-model="query"
          icon="i-mdi-magnify"
          :placeholder="tr('Search logs')"
          :aria-label="tr('Search logs')"
          class="w-60 max-w-full"
        /><USelect v-model="level" :items="levels" :aria-label="tr('Log level')" class="w-36" />
      </div>
      <div class="flex gap-2">
        <UButton
          id="refresh-logs"
          color="neutral"
          :loading="loading"
          :label="tr('Reload Logs')"
          @click="refreshLogs"
          icon="mdi:refresh"
        /><UButton
          :title="tr('Scroll to bottom')"
          :aria-label="tr('Scroll to bottom')"
          color="neutral"
          @click="scrollToBottom"
          icon="mdi:arrow-down"
        />
      </div>
    </div>
    <p v-if="failed" class="negative p-4" role="status">
      {{ tr('Could not load logs. Refresh to retry.') }}
    </p>
    <div
      ref="scrollContainer"
      class="log-content"
      tabindex="0"
      :aria-label="tr('Logs')"
      :aria-busy="loading"
    >
      <div v-if="!logs.length" class="p-12 text-center muted">
        {{ loading ? tr('Loading…') : tr('No matching logs') }}
      </div>
      <div v-for="(log, index) in logs" :key="index" class="log-row">
        <time>{{ log[0] }}</time
        ><span
          class="log-level"
          :class="{
            negative: log[3] === 'ERROR' || log[3] === 'CRITICAL',
            'text-amber-500': log[3] === 'WARNING',
          }"
          >{{ log[3] }}</span
        ><span class="log-message"
          ><span class="muted">{{ log[2] }} · </span>{{ log[4] }}</span
        >
      </div>
    </div>
    <div class="log-footer">
      {{ tr('{0} matching records', { 0: logs.length }) }} ·
      {{ tr('Server log messages are shown in their original language.') }}
    </div>
  </section>
</template>
<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 350px;
}
.log-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  padding: 20px;
  gap: 12px;
  border-bottom: 1px solid var(--workspace-border);
}
.log-content {
  overflow: auto;
  flex: 1;
  padding: 10px 0;
  font:
    12px/1.8 'SFMono-Regular',
    Consolas,
    'Liberation Mono',
    monospace;
}
.log-row {
  display: grid;
  grid-template-columns: 176px 65px minmax(0, 1fr);
  gap: 14px;
  padding: 7px 20px;
  border-bottom: 1px solid #7794fa08;
}
.log-row:hover {
  background: var(--workspace-elevated);
}
time {
  color: var(--workspace-muted);
}
.log-level {
  font-size: 10px;
  font-weight: 650;
}
.log-message {
  overflow-wrap: anywhere;
}
.log-footer {
  padding: 14px 20px;
  color: var(--workspace-muted);
  font-size: 11px;
  border-top: 1px solid var(--workspace-border);
}
@media (max-width: 767px) {
  .log-toolbar {
    padding: 16px;
  }
  .log-row {
    grid-template-columns: minmax(0, 1fr) 65px;
    gap: 4px 12px;
    padding: 12px 16px;
  }
  .log-message {
    grid-column: 1 / -1;
  }
}
</style>
