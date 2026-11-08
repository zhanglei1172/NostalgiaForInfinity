<script setup lang="ts">
import { tr, language } from '@/i18n';
import type { AccountPoint } from '@/utils/accountMetrics';
import type { EChartsOption } from 'echarts';
import ECharts from 'vue-echarts';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { LineChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  AriaComponent,
  MarkLineComponent,
} from 'echarts/components';
use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, AriaComponent, MarkLineComponent]);
const props = defineProps<{
  history: AccountPoint[];
  observations: AccountPoint[];
  captureStart?: number;
  currency: string;
  initial?: number;
  loading: boolean;
  historyError: boolean;
  storageAvailable: boolean;
}>();
const settings = useSettingsStore();
const range = ref(30);
const rangeOptions = computed(() => [
  { label: tr('24 hours'), value: 1 },
  { label: tr('7 days'), value: 7 },
  { label: tr('30 days'), value: 30 },
  { label: tr('All available'), value: 0 },
]);
const now = computed(() => Math.max(Date.now(), props.observations.at(-1)?.time ?? 0));
const inRange = (points: AccountPoint[]) =>
  points.filter(
    (p) =>
      p.time <= now.value && (range.value === 0 || p.time >= now.value - range.value * 86400000),
  );
const history = computed(() => inRange(props.history));
const observations = computed(() => inRange(props.observations));
const hasData = computed(() => history.value.length + observations.value.length > 0);
const money = (v: number) =>
  new Intl.NumberFormat(language.value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v);
const date = (v: number) =>
  new Intl.DateTimeFormat(language.value, {
    timeZone: settings.timezone,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(v);
const fullDate = (value: number) =>
  new Intl.DateTimeFormat(language.value, {
    timeZone: settings.timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(value);
const latest = computed(() => observations.value.at(-1) ?? history.value.at(-1));
const tableRows = computed(() =>
  [
    ...history.value.map((p) => ({
      ...p,
      source:
        props.captureStart && p.time < props.captureStart
          ? tr('Reconstructed history')
          : tr('Daily wallet value'),
    })),
    ...observations.value.map((p) => ({ ...p, source: tr('Observed equity') })),
  ].sort((a, b) => b.time - a.time),
);
const option = computed<EChartsOption>(() => {
  const dark = settings.isDarkTheme;
  const equityColor = dark ? '#4edfc2' : '#087f5b';
  const walletColor = dark ? '#f2b55e' : '#a86606';
  const text = dark ? '#96a5bc' : '#64748b';
  const border = dark ? '#243045' : '#e3e8f0';
  const capture = props.captureStart ?? 0;
  const observedData: [number, number | null][] = [];
  observations.value.forEach((p, i) => {
    const previous = observations.value[i - 1];
    // Never bridge periods where the browser was not collecting observations.
    if (previous && p.time - previous.time > 600000) observedData.push([previous.time + 1, null]);
    observedData.push([p.time, p.value]);
  });
  const allValues = [...history.value, ...observations.value].map((p) => p.value);
  const low = Math.min(...allValues);
  const high = Math.max(...allValues);
  const padding = Math.max((high - low) * 0.18, Math.abs(high) * 0.001, 0.01);
  return {
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    backgroundColor: 'transparent',
    aria: {
      enabled: true,
      label: {
        description: tr('Account equity over time. A data table is available below the chart.'),
      },
    },
    grid: { left: 12, right: 22, top: 30, bottom: 14, containLabel: true },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      confine: true,
      backgroundColor: dark ? '#182234' : '#fff',
      borderColor: border,
      textStyle: { color: dark ? '#e9eef8' : '#182337' },
      formatter: (params) => {
        const points = (Array.isArray(params) ? params : [params]) as {
          seriesName: string;
          value: [number, number | null];
        }[];
        const first = points[0];
        return first
          ? `${fullDate(first.value[0])} · ${settings.timezone}\n${points
              .filter((p) => typeof p.value[1] === 'number')
              .map((p) => `${p.seriesName}  ${money(p.value[1]!)} ${props.currency}`)
              .join('\n')}`
          : '';
      },
      valueFormatter: (v) => (typeof v === 'number' ? `${money(v)} ${props.currency}` : '—'),
      axisPointer: { type: 'line', lineStyle: { color: '#8a9dbd', type: 'dashed' } },
    },
    xAxis: {
      type: 'time',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: text, hideOverlap: true, formatter: (value) => date(value) },
      axisPointer: { label: { formatter: (params) => date(Number(params.value)) } },
    },
    yAxis: {
      type: 'value',
      min: Number.isFinite(low) ? low - padding : undefined,
      max: Number.isFinite(high) ? high + padding : undefined,
      splitNumber: 4,
      splitLine: { lineStyle: { color: border, type: 'dashed' } },
      axisLabel: { color: text, formatter: (value) => money(value) },
    },
    series: [
      {
        name: tr('Reconstructed history'),
        type: 'line',
        data: history.value.filter((p) => p.time < capture).map((p) => [p.time, p.value]),
        lineStyle: { color: walletColor, width: 2, type: 'dashed' },
        itemStyle: { color: walletColor },
        symbolSize: 5,
        showSymbol: true,
      },
      {
        name: tr('Daily wallet value'),
        type: 'line',
        data: history.value.filter((p) => p.time >= capture).map((p) => [p.time, p.value]),
        lineStyle: { color: walletColor, width: 2 },
        itemStyle: { color: walletColor },
        symbolSize: 6,
        showSymbol: true,
      },
      {
        name: tr('Observed equity'),
        type: 'line',
        data: observedData,
        connectNulls: false,
        smooth: false,
        showSymbol: observations.value.length < 3,
        symbolSize: 9,
        itemStyle: { color: equityColor },
        lineStyle: { width: 3, color: equityColor },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: '#4edfc220' },
              { offset: 1, color: '#4edfc200' },
            ],
          },
        },
      },
    ],
  };
});
</script>
<template>
  <section
    class="workspace-panel equity-panel"
    :aria-label="tr('Account equity over time')"
    :aria-busy="loading"
    data-testid="equity-panel"
  >
    <div class="equity-heading">
      <div>
        <p class="eyebrow">{{ tr('CAPITAL OVERVIEW') }}</p>
        <h2>{{ tr('Account equity over time') }}</h2>
        <p class="muted text-xs mt-2">
          {{ tr('Account valuation, including open positions') }} · {{ currency }}
        </p>
      </div>
      <USelect
        v-model="range"
        :items="rangeOptions"
        :aria-label="tr('Chart date range')"
        class="w-36"
      />
    </div>
    <div class="equity-readout">
      <div>
        <span class="legend-dot" :class="observations.length ? 'equity-dot' : 'wallet-dot'" />{{
          observations.length ? tr('Observed equity') : tr('Daily wallet value')
        }}<strong class="financial-value"
          >{{ latest ? money(latest.value) : '—' }} <small>{{ currency }}</small></strong
        >
      </div>
      <span class="muted text-xs">{{
        latest ? `${date(latest.time)} · ${settings.timezone}` : tr('Waiting for data')
      }}</span>
    </div>
    <div class="equity-legend">
      <span><i class="legend-dot equity-dot" />{{ tr('Observed equity') }}</span
      ><span><i class="legend-dot wallet-dot" />{{ tr('Daily wallet value') }}</span
      ><span v-if="captureStart && history.some((p) => p.time < (captureStart ?? 0))"
        ><i class="legend-dash" />{{ tr('Reconstructed history') }}</span
      >
    </div>
    <div class="equity-canvas">
      <ECharts v-if="hasData" :option="option" autoresize />
      <div v-else class="chart-empty">
        <UIcon name="i-mdi-chart-timeline-variant" class="size-10 muted" /><strong>{{
          loading ? tr('Loading account history…') : tr('No account data in this range')
        }}</strong>
        <p>{{ tr('Use refresh to retry, or choose a wider date range.') }}</p>
      </div>
    </div>
    <div class="equity-caption">
      <UIcon name="i-mdi-information-outline" class="size-4 shrink-0 mt-0.5" />
      <div>
        {{
          tr(
            'Daily values come from the bot. Dashed history was reconstructed and does not include historical unrealized P&L.',
          )
        }}
        {{
          tr(
            'Live equity is sampled while this dashboard is open, stored only in this browser for up to 31 days, at 5-minute resolution. Gaps indicate no observations.',
          )
        }}
        <p v-if="historyError" class="negative mt-2" role="status">
          {{
            tr(
              'Could not load daily history. Refresh to retry; existing observations are retained.',
            )
          }}
        </p>
        <p v-if="!storageAvailable" class="negative mt-2" role="status">
          {{ tr('Browser storage is unavailable. New observations last for this session only.') }}
        </p>
      </div>
    </div>
    <details class="equity-data">
      <summary>
        {{ tr('View chart data') }} <span class="muted">({{ tableRows.length }})</span>
      </summary>
      <div class="max-h-64 overflow-auto">
        <table class="w-full">
          <thead>
            <tr>
              <th>{{ tr('Date') }} ({{ settings.timezone }})</th>
              <th>{{ tr('Source') }}</th>
              <th>{{ tr('Value') }} ({{ currency }})</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in tableRows" :key="index">
              <td>{{ fullDate(row.time) }}</td>
              <td>{{ row.source }}</td>
              <td>{{ money(row.value) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </section>
</template>
<style scoped>
.equity-panel {
  --equity-color: #087f5b;
  --wallet-color: #a86606;
  padding: 26px 28px 0;
}
:global(.dark) .equity-panel {
  --equity-color: #4edfc2;
  --wallet-color: #f2b55e;
}
.equity-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.equity-heading h2 {
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.025em;
}
.equity-readout {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin: 28px 0 18px;
}
.equity-readout > div {
  font-size: 12px;
  color: var(--workspace-muted);
}
.equity-readout strong {
  display: block;
  color: var(--workspace-text);
  font-size: 38px;
  font-weight: 650;
  margin-top: 6px;
}
.equity-readout small {
  font-size: 14px;
  color: var(--workspace-muted);
  font-weight: 500;
}
.legend-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 7px;
}
.equity-dot {
  background: var(--equity-color);
}
.wallet-dot {
  background: var(--wallet-color);
}
.legend-dash {
  display: inline-block;
  width: 16px;
  border-top: 2px dashed var(--wallet-color);
  margin-right: 7px;
}
.equity-legend {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--workspace-muted);
}
.equity-canvas {
  height: 345px;
  margin: 10px -10px 10px;
}
.echarts {
  width: 100%;
  height: 100%;
}
.chart-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  text-align: center;
}
.chart-empty p {
  font-size: 12px;
  color: var(--workspace-muted);
}
.equity-caption {
  border-top: 1px solid var(--workspace-border);
  padding: 18px 0;
  display: flex;
  gap: 8px;
  font-size: 11px;
  line-height: 1.8;
  color: var(--workspace-muted);
}
.equity-data {
  border-top: 1px solid var(--workspace-border);
  font-size: 12px;
}
.equity-data summary {
  cursor: pointer;
  padding: 14px 0;
  color: var(--workspace-accent);
}
@media (max-width: 767px) {
  .equity-panel {
    padding: 20px 16px 0;
  }
  .equity-heading {
    align-items: flex-start;
  }
  .equity-heading h2 {
    font-size: 17px;
  }
  .equity-readout {
    flex-direction: column;
    align-items: flex-start;
    margin-top: 22px;
  }
  .equity-readout strong {
    font-size: 30px;
  }
  .equity-canvas {
    height: 270px;
  }
  .equity-heading :deep(button) {
    width: 104px;
  }
}
</style>
