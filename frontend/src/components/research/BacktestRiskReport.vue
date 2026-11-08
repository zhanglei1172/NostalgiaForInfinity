<script setup lang="ts">
import { language, tr } from '@/i18n';
import type { StrategyBacktestResult, WalletHistory } from '@/types';
import { backtestDrawdown } from '@/utils/backtestDrawdown';
import type { EChartsOption } from 'echarts';
import ECharts from 'vue-echarts';
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { CanvasRenderer } from 'echarts/renderers';
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
} from 'echarts/components';
use([LineChart, CanvasRenderer, AriaComponent, DataZoomComponent, GridComponent, TooltipComponent]);

const props = defineProps<{ result: StrategyBacktestResult; filename?: string }>();
const bots = useBotStore();
const headingId = useId();
const wallet = shallowRef<WalletHistory>();
const loading = ref(false);
const failed = ref(false);
let generation = 0;
const risk = computed(() => backtestDrawdown(props.result, wallet.value));
const maximum = computed(() => risk.value.maximum);
const canLoad = computed(() => !!props.filename);
const source = computed(() =>
  tr(
    {
      wallet: 'Wallet valuation samples',
      wallet_summary: 'Engine wallet summary',
      closed_trades: 'Closed-trade profit curve',
      unavailable: 'Insufficient risk data',
    }[risk.value.source],
  ),
);
const percent = (value: number | null) => (value === null ? '—' : formatPercent(value, 2));
const money = (value: number | null) =>
  value === null
    ? '—'
    : `${new Intl.NumberFormat(language.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)} ${props.result.stake_currency}`;
function duration(value: number | null) {
  if (value === null) return '—';
  const seconds = Math.floor(value / 1000);
  if (seconds < 60) return tr('{seconds} seconds', { seconds });
  return tr('{days}d {hours}h {minutes}m', {
    days: Math.floor(seconds / 86400),
    hours: Math.floor((seconds % 86400) / 3600),
    minutes: Math.floor((seconds % 3600) / 60),
  });
}
function date(value: number | null | undefined) {
  return value == null
    ? '—'
    : new Date(value).toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
}
const recovery = computed(() => {
  if (!maximum.value)
    return risk.value.maxRatio === 0 ? tr('No drawdown occurred') : tr('Not available');
  return maximum.value.recovered === null
    ? tr('Not recovered by test end')
    : duration(maximum.value.recovered - maximum.value.peak);
});
async function load() {
  const sequence = ++generation;
  wallet.value = undefined;
  loading.value = false;
  failed.value = false;
  if (!props.filename) return;
  const filename = props.filename.replace(/\.(zip|json)$/, '');
  const strategy = props.result.strategy_name;
  if (!/^[A-Za-z0-9_-]+$/.test(filename) || !/^[A-Za-z0-9_]+$/.test(strategy)) {
    failed.value = true;
    return;
  }
  const id = bots.selectedBot;
  const api = useApi(useLoginInfo(id), id).api;
  const direct = bots.activeBot.canRunBacktest && !bots.activeBot.botState.nfi_live_management;
  loading.value = true;
  try {
    const data = await api<WalletHistory>(
      (direct ? '' : '/research') + `/backtest/history/${filename}/${strategy}/wallet`,
    );
    if (sequence !== generation) return;
    if (!Array.isArray(data?.data) || !Array.isArray(data?.columns))
      throw new Error('wallet_history_invalid');
    wallet.value = data;
    if (backtestDrawdown(props.result, data).source !== 'wallet') failed.value = true;
  } catch {
    if (sequence === generation) failed.value = true;
  } finally {
    if (sequence === generation) loading.value = false;
  }
}
watch(() => [props.result, props.filename, bots.selectedBot], load, { immediate: true });
onBeforeUnmount(() => {
  ++generation;
});
const option = computed<EChartsOption>(() => ({
  animation: false,
  useUTC: true,
  aria: { enabled: true },
  grid: { top: 20, bottom: 65, left: 65, right: 25 },
  tooltip: {
    trigger: 'axis',
    renderMode: 'richText',
    valueFormatter: (value) => formatPercent(-Number(value) / 100, 2),
  },
  xAxis: {
    type: 'time',
    axisLabel: {
      color: '#94a3b8',
      formatter: (value: number) => new Date(value).toISOString().slice(0, 10),
    },
  },
  yAxis: {
    type: 'value',
    max: 0,
    axisLabel: { color: '#94a3b8', formatter: '{value}%' },
    splitLine: { lineStyle: { color: '#94a3b820' } },
  },
  dataZoom: [
    { type: 'inside', filterMode: 'none' },
    { type: 'slider', height: 18, bottom: 10, filterMode: 'none' },
  ],
  series: [
    {
      name: tr('Drawdown'),
      type: 'line',
      data: risk.value.points.map((point) => [point.timestamp, -point.ratio * 100]),
      showSymbol: false,
      sampling: 'minmax',
      lineStyle: { color: '#f87171', width: 1.5 },
      areaStyle: { color: '#f8717128' },
    },
  ],
}));
</script>

<template>
  <section class="workspace-panel risk-report mb-6" :aria-labelledby="headingId">
    <div class="panel-heading flex flex-wrap gap-3 justify-between items-center">
      <div>
        <h2 :id="headingId">{{ tr('Drawdown and recovery') }}</h2>
        <p class="muted text-xs mt-2 font-normal">
          {{ result.strategy_name }} · {{ result.backtest_start }} → {{ result.backtest_end }} UTC
        </p>
        <p class="muted text-xs mt-2 font-normal">{{ tr('Basis') }}: {{ source }}</p>
      </div>
      <UButton v-if="canLoad && failed" color="neutral" :loading="loading" @click="load">{{
        tr('Retry wallet history')
      }}</UButton>
    </div>
    <p v-if="loading" role="status" class="p-6 muted text-sm">
      {{ tr('Loading wallet history for drawdown analysis…') }}
    </p>
    <template v-else>
      <UAlert
        v-if="risk.source !== 'wallet'"
        class="mx-6 mt-6"
        color="warning"
        :title="
          tr(
            'Wallet history is unavailable. Recovery cannot be inferred from the engine’s peak-to-trough duration.',
          )
        "
        :description="
          risk.source === 'closed_trades'
            ? tr(
                'The fallback uses final trade profits and excludes floating losses and the timing of partial exits. It may understate NFI drawdowns.',
              )
            : tr(
                'Only available summary metrics are shown; missing recovery dates remain unavailable.',
              )
        "
      />
      <div class="risk-metrics">
        <div>
          <span>{{ tr('Maximum drawdown (%)') }}</span
          ><strong>{{ percent(risk.maxRatio) }}</strong>
        </div>
        <div>
          <span>{{ tr('Maximum monetary drawdown') }}</span
          ><strong>{{ money(risk.maxAmount) }}</strong>
        </div>
        <div>
          <span>{{ tr('Max drawdown recovery (peak to recovery)') }}</span
          ><strong>{{ recovery }}</strong
          ><small v-if="maximum?.recovered === null && risk.end !== null">{{
            tr('Observed underwater: {duration}', { duration: duration(risk.end - maximum.peak) })
          }}</small>
        </div>
        <div>
          <span>{{ tr('Longest underwater period') }}</span
          ><strong>{{ duration(risk.longestMs) }}</strong
          ><small v-if="risk.longest">{{
            risk.longest.recovered === null ? tr('Still underwater at test end') : tr('Recovered')
          }}</small>
        </div>
      </div>
      <dl v-if="maximum" class="risk-details px-6 pb-6">
        <div>
          <dt>{{ tr('Peak before maximum percentage drawdown') }}</dt>
          <dd>{{ date(maximum.peak) }}</dd>
        </div>
        <div>
          <dt>{{ tr('Trough of maximum percentage drawdown') }}</dt>
          <dd>{{ date(maximum.trough) }}</dd>
        </div>
        <div>
          <dt>{{ tr('First recovery to the previous peak') }}</dt>
          <dd>
            {{
              maximum.recovered === null ? tr('Not recovered by test end') : date(maximum.recovered)
            }}
          </dd>
        </div>
        <div>
          <dt>{{ tr('Decline duration (peak to trough)') }}</dt>
          <dd>{{ duration(maximum.trough - maximum.peak) }}</dd>
        </div>
        <div>
          <dt>{{ tr('Recovery after trough') }}</dt>
          <dd>
            {{
              maximum.recovered === null
                ? tr('Not recovered by test end')
                : duration(maximum.recovered - maximum.trough)
            }}
          </dd>
        </div>
        <div>
          <dt>{{ tr('Amount at maximum percentage drawdown') }}</dt>
          <dd>{{ money(maximum.amount) }}</dd>
        </div>
      </dl>
      <ECharts
        v-if="risk.points.length"
        :option="option"
        autoresize
        class="drawdown-chart"
        :aria-label="tr('Backtest underwater chart')"
      />
      <p class="px-6 pb-6 muted text-xs leading-relaxed">
        {{
          tr(
            'Recovery is the first saved observation at or above the previous peak. The clock starts at the last peak before the decline; an unrecovered period is measured through test end. Maximum percentage and monetary drawdowns may occur in different periods.',
          )
        }}
        {{
          risk.source === 'wallet'
            ? tr(
                'Wallet valuation includes saved position valuations and partial exits. Drawdowns between saved samples are not observable.',
              )
            : ''
        }}
      </p>
    </template>
  </section>
</template>

<style scoped>
.risk-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
  padding: 24px;
}
.risk-metrics span,
.risk-details dt {
  display: block;
  color: var(--workspace-muted);
  font-size: 12px;
  margin-bottom: 9px;
}
.risk-metrics strong {
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}
.risk-metrics small {
  display: block;
  color: var(--workspace-muted);
  font-size: 12px;
  margin-top: 7px;
}
.risk-details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  font-size: 13px;
}
.drawdown-chart {
  height: 310px;
  width: 100%;
}
@media (max-width: 767px) {
  .risk-metrics,
  .risk-details {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .risk-metrics strong {
    font-size: 16px;
  }
}
@media (max-width: 420px) {
  .risk-details {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
