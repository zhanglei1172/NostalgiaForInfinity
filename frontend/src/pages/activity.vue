<script setup lang="ts">
import { language, tr } from '@/i18n';
import type { StrategyActivity } from '@/types/activity';

const bots = useBotStore();
const data = ref<StrategyActivity>();
const busy = ref(false);
const error = ref(false);
const search = ref('');
let generation = 0;
const reasons: Record<string, string> = {
  stopped: 'Bot stopped: no strategy analysis or position management until you start it.',
  paused:
    'Entries paused: existing positions are managed, but new entries and position increases are disabled.',
  reloading: 'Bot configuration is reloading.',
  slots_full: 'All position slots are occupied.',
  global_lock: 'A global protection lock blocks new entries.',
  empty_pool: 'The current pair pool is empty.',
  position_open: 'An existing position excludes this pair from new initial entries.',
  pair_locked: 'A protection lock blocks new entries for this pair.',
  no_analysis: 'No analyzed candles cached yet. Start the bot and allow time for warm-up.',
  stale_candle: 'The cached candle is stale; it cannot establish a current entry opportunity.',
  no_entry_signal: 'The latest cached candle has no long entry signal.',
  signal_conflict: 'Entry conflicts with an exit or short signal on the same candle.',
  entry_candidate:
    'A long entry signal exists. Further checks and order execution are still required.',
  grind_coins: 'NFI rejected entry: pair is outside the grind-mode coin list.',
  grind_slots: 'NFI rejected entry: grind-mode position limit reached.',
  top_coins: 'NFI rejected entry: pair is outside the top-coin list.',
  mode_slots: 'NFI rejected entry: insufficient slots for this mode.',
  slippage: 'NFI rejected entry: entry price exceeds slippage tolerance.',
  entry_denied: 'The strategy rejected entry; no specific reason was recorded.',
};
const explain = (code: string) => tr(reasons[code] ?? 'No detailed reason was recorded.');
const pairs = computed(() =>
  (data.value?.pairs ?? []).filter((item) => item.pair.includes(search.value.trim().toUpperCase())),
);
const stamp = (value: string | null) =>
  value ? new Date(value).toLocaleString(language.value) : '—';
async function refresh() {
  if (busy.value || !bots.hasBots) return;
  const current = generation;
  const id = bots.selectedBot;
  busy.value = true;
  try {
    const result = await useApi(useLoginInfo(id), id).api<StrategyActivity>('/strategy-activity');
    if (current !== generation) return;
    data.value = result;
    error.value = false;
  } catch {
    if (current === generation) error.value = true;
  } finally {
    if (current === generation) busy.value = false;
  }
}
watch(
  () => bots.selectedBot,
  () => {
    ++generation;
    data.value = undefined;
    busy.value = false;
    error.value = false;
    void refresh();
  },
);
useIntervalFn(() => {
  if (bots.globalAutoRefresh && bots.activeBot?.autoRefresh) void refresh();
}, 15000);
onMounted(refresh);
onBeforeUnmount(() => {
  ++generation;
});
</script>

<template>
  <div class="workspace-page activity-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ data?.exchange.toUpperCase() ?? 'NFI' }} · {{ data?.strategy }}</p>
        <h1>{{ tr('Strategy activity') }}</h1>
        <p>{{ tr('See observed signals, execution blocks and recent fills.') }}</p>
      </div>
      <UButton icon="i-mdi-refresh" color="neutral" :loading="busy" @click="refresh">{{
        tr('Refresh')
      }}</UButton>
    </div>
    <UAlert
      v-if="error"
      role="alert"
      color="warning"
      class="mb-5"
      :title="tr('Strategy activity could not be refreshed. Any displayed data may be stale.')"
    />
    <p v-if="!data && busy">{{ tr('Loading…') }}</p>
    <template v-if="data">
      <section class="workspace-panel p-5 mb-5">
        <div class="flex flex-wrap items-center gap-3 mb-4">
          <h2>{{ tr('Current entry status') }}</h2>
          <UBadge color="neutral">{{
            tr(
              data.state === 'running'
                ? 'Running'
                : data.state === 'paused'
                  ? 'Paused'
                  : data.state === 'stopped'
                    ? 'Stopped'
                    : 'Reloading',
            )
          }}</UBadge>
          <UBadge color="neutral">{{ tr(data.dry_run ? 'Paper trading' : 'Live trading') }}</UBadge>
        </div>
        <p class="muted mb-3">
          {{
            tr('Open positions: {open} · Free slots: {free} · Pairs: {pairs}', {
              open: data.open_trades,
              free: data.free_slots,
              pairs: data.pair_count,
            })
          }}
        </p>
        <ul v-if="data.reasons.length" class="space-y-2">
          <li v-for="reason in data.reasons" :key="reason">{{ explain(reason) }}</li>
        </ul>
        <p v-else>
          {{ tr('No global entry block observed. Per-pair and order checks still apply.') }}
        </p>
        <p class="muted text-xs mt-4">
          {{ tr('Updated at {0}', { 0: stamp(data.as_of) }) }} ·
          {{ tr('Times use your browser timezone.') }}
        </p>
      </section>
      <section class="workspace-panel p-5 mb-5">
        <div class="flex flex-wrap gap-3 justify-between mb-4">
          <h2>{{ tr('Latest analyzed signals') }} · {{ data.timeframe }}</h2>
          <UInput
            v-model="search"
            :aria-label="tr('Filter pairs')"
            :placeholder="tr('Filter pairs')"
            icon="i-mdi-magnify"
          />
        </div>
        <p class="muted text-sm mb-4">
          {{
            tr(
              'Cached signal facts only. A signal does not prove an order was submitted. Missing signals do not reveal which individual indicator failed.',
            )
          }}
        </p>
        <p v-if="!pairs.length" class="muted">
          {{ tr('No matching pair snapshots are available.') }}
        </p>
        <div class="activity-grid">
          <article v-for="item in pairs" :key="item.pair" class="activity-card">
            <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
              <strong>{{ item.pair }}</strong>
              <UBadge :color="item.signal === 'entry' ? 'info' : 'neutral'">{{
                tr(
                  item.signal === 'entry'
                    ? 'Entry signal'
                    : item.signal === 'none'
                      ? 'No entry signal'
                      : item.signal === 'conflict'
                        ? 'Conflicting signals'
                        : 'No analysis',
                )
              }}</UBadge>
            </div>
            <p class="muted text-xs">{{ tr('Candle time') }}: {{ stamp(item.candle_at) }}</p>
            <p class="text-sm mt-2">
              {{ tr('Entry tag') }}: <code>{{ item.entry_tag || '—' }}</code>
            </p>
            <p v-if="item.exit_tag" class="text-sm">
              {{ tr('Exit tag') }}: <code>{{ item.exit_tag }}</code>
            </p>
            <ul class="text-sm mt-3 space-y-2">
              <li v-for="reason in item.reasons" :key="reason">{{ explain(reason) }}</li>
            </ul>
            <p v-if="item.lock_until" class="muted text-xs mt-2">
              {{ tr('Locked until') }}: {{ stamp(item.lock_until) }}
            </p>
          </article>
        </div>
      </section>
      <section class="workspace-panel p-5 mb-5">
        <h2 class="mb-3">{{ tr('Recent fills') }}</h2>
        <p class="muted text-sm mb-4">
          {{
            tr(
              'Up to 30 orders with executed quantity, including partial fills. Order tags are recorded facts; an empty tag has no recorded explanation.',
            )
          }}
        </p>
        <p v-if="!data.fills.length" class="muted">
          {{ tr('No fills in this bot database yet.') }}
        </p>
        <div class="activity-grid">
          <article v-for="(fill, index) in data.fills" :key="index" class="activity-card">
            <div class="flex flex-wrap gap-2 justify-between">
              <strong>{{ fill.pair }}</strong
              ><span>{{ tr(fill.side === 'buy' ? 'Buy' : 'Sell') }}</span>
            </div>
            <p class="muted text-xs mt-2">{{ stamp(fill.at) }} · #{{ fill.trade_id }}</p>
            <p class="text-sm mt-2">
              {{ tr('Filled quantity') }}: {{ fill.filled }} · {{ tr('Price') }}:
              {{ fill.price ?? '—' }}
            </p>
            <p class="text-sm">
              {{ tr('Order tag') }}: <code>{{ fill.tag || '—' }}</code>
            </p>
            <p v-if="fill.exit_reason" class="text-sm">
              {{ tr('Final exit reason') }}: <code>{{ fill.exit_reason }}</code>
            </p>
            <p v-if="fill.order_open" class="muted text-sm">
              {{ tr('Partially filled; order is still open.') }}
            </p>
          </article>
        </div>
      </section>
      <section class="workspace-panel p-5">
        <h2 class="mb-3">{{ tr('Recorded entry rejections') }}</h2>
        <p class="muted text-sm mb-4">
          {{
            tr(
              'Up to 100 recognized rejection events since {time}. This journal resets on bot restart or configuration reload; trade records remain in the database.',
              { time: stamp(data.journal_since) },
            )
          }}
        </p>
        <p v-if="!data.rejections.length" class="muted">
          {{
            tr(
              'No explicit rejection events recorded in this session. This does not mean every pair met the strategy conditions.',
            )
          }}
        </p>
        <ol class="space-y-4">
          <li v-for="(event, index) in data.rejections" :key="index" class="activity-event">
            <p>
              <strong>{{ event.pair }}</strong> ·
              <time class="muted text-xs">{{ stamp(event.at) }}</time>
            </p>
            <p class="text-sm mt-1">{{ explain(event.reason) }}</p>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>

<style scoped>
.activity-page {
  max-width: 1400px;
}
.activity-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.activity-card {
  padding: 16px;
  border: 1px solid var(--ui-border);
  border-radius: 10px;
  overflow-wrap: anywhere;
}
.activity-event {
  border-left: 2px solid var(--ui-border);
  padding-left: 12px;
}
@media (max-width: 760px) {
  .activity-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
