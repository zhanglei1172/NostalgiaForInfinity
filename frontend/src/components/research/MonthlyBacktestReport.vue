<script setup lang="ts">
import { tr, language } from '@/i18n';
import { monthlyBacktest } from '@/utils/monthlyBacktest';
import type { StrategyBacktestResult } from '@/types';
import type { EChartsOption } from 'echarts';
import ECharts from 'vue-echarts';
import { use } from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { CanvasRenderer } from 'echarts/renderers';
import { AriaComponent, GridComponent, TooltipComponent } from 'echarts/components';
use([BarChart, CanvasRenderer, AriaComponent, GridComponent, TooltipComponent]);
const props = defineProps<{ result: StrategyBacktestResult; filename?: string }>();
const colors = useColorStore();
const rows = computed(() => monthlyBacktest(props.result));
const currency = computed(() => props.result.stake_currency);
const money = (value: number, digits = 2) =>
  new Intl.NumberFormat(language.value, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
const option = computed<EChartsOption>(() => ({
  animation: false,
  aria: { enabled: true },
  grid: { top: 20, bottom: 50, left: 65, right: 20 },
  tooltip: {
    trigger: 'axis',
    renderMode: 'richText',
    valueFormatter: (value) => `${money(Number(value), 2)} ${currency.value}`,
  },
  xAxis: {
    type: 'category',
    data: rows.value.map((r) => r.month),
    axisLabel: { rotate: 30, color: '#94a3b8' },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#94a3b8' },
    splitLine: { lineStyle: { color: '#94a3b820' } },
  },
  series: [
    {
      type: 'bar',
      data: rows.value.map((r) => ({
        value: r.profit,
        itemStyle: {
          color: r.profit >= 0 ? colors.colorProfit : colors.colorLoss,
          borderRadius: [4, 4, 0, 0],
        },
      })),
      barMaxWidth: 36,
    },
  ],
}));
function download() {
  const data = [
    [
      tr('Month (UTC)'),
      tr('Monthly profit'),
      tr('Monthly return'),
      tr('Opening balance'),
      tr('Closing balance'),
      tr('Trades'),
      tr('Wins'),
      tr('Losses'),
      tr('Coverage'),
    ],
    ...rows.value.map((row) => [
      row.month,
      row.profit.toFixed(8),
      row.returnRatio === null ? '' : (row.returnRatio * 100).toFixed(4) + '%',
      row.openingBalance.toFixed(8),
      row.closingBalance.toFixed(8),
      row.trades,
      row.wins,
      row.losses,
      row.partial ? tr('Partial month') : tr('Full month'),
    ]),
  ];
  const blob = new Blob(
    [
      '\uFEFF' +
        data
          .map((line) => line.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(','))
          .join('\r\n'),
    ],
    { type: 'text/csv;charset=utf-8' },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `monthly-${props.result.strategy_name}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
</script>
<template>
  <BacktestRiskReport :result="result" :filename="filename" />
  <section class="workspace-panel monthly-report">
    <div class="panel-heading flex justify-between gap-3 flex-wrap items-center">
      <div>
        <h2>{{ tr('Monthly backtest returns') }}</h2>
        <p class="muted text-xs mt-2 font-normal">
          {{ result.strategy_name }} · {{ result.backtest_start }} → {{ result.backtest_end }} UTC
        </p>
      </div>
      <UButton color="neutral" icon="i-mdi-download" @click="download">{{
        tr('Export monthly CSV')
      }}</UButton>
    </div>
    <div class="report-metrics">
      <div>
        <span>{{ tr('Starting capital:') }}</span
        ><strong>{{ money(result.starting_balance, 2) }} {{ currency }}</strong>
      </div>
      <div>
        <span>{{ tr('Net backtest profit') }}</span
        ><strong
          :style="{ color: result.profit_total_abs >= 0 ? colors.colorProfit : colors.colorLoss }"
          >{{ money(result.profit_total_abs, 2) }} {{ currency }}</strong
        >
      </div>
      <div>
        <span>{{ tr('Total return') }}</span
        ><strong>{{ formatPercent(result.profit_total, 2) }}</strong>
      </div>
      <div>
        <span>{{ tr('Total trades') }}</span
        ><strong>{{ result.total_trades }}</strong>
      </div>
    </div>
    <p class="px-6 text-xs muted">{{ tr('Tested pairs') }}: {{ result.pairlist.join(', ') }}</p>
    <ECharts
      :option="option"
      autoresize
      class="monthly-chart"
      :aria-label="tr('Monthly backtest returns')"
    />
    <div class="overflow-x-auto px-6">
      <table class="monthly-table">
        <caption class="sr-only">
          {{
            tr('Monthly backtest returns')
          }}
          ({{
            currency
          }})
        </caption>
        <thead>
          <tr>
            <th>{{ tr('Month (UTC)') }}</th>
            <th>{{ tr('Monthly profit') }} ({{ currency }})</th>
            <th>{{ tr('Monthly return') }}</th>
            <th>{{ tr('Closing balance') }} ({{ currency }})</th>
            <th>{{ tr('Trades') }}</th>
            <th>{{ tr('Win Rate') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.month">
            <th>
              {{ row.month }}
              <small v-if="row.partial" class="muted">{{ tr('Partial month') }}</small>
            </th>
            <td :style="{ color: row.profit >= 0 ? colors.colorProfit : colors.colorLoss }">
              {{ money(row.profit, 2) }}
            </td>
            <td>{{ row.returnRatio === null ? '—' : formatPercent(row.returnRatio, 2) }}</td>
            <td>{{ money(row.closingBalance, 2) }}</td>
            <td>{{ row.trades }}</td>
            <td>{{ row.trades ? formatPercent(row.wins / row.trades, 2) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="result.total_trades === 0" class="p-6 muted text-sm">
      {{ tr('No trades were triggered in this backtest. Monthly profit is zero.') }}
    </p>
    <p class="p-6 muted text-xs leading-relaxed">
      {{
        tr(
          'Profits are grouped by closing month in UTC, including fees and exits forced at the end of the test. Monthly return divides realized profit by the opening realized balance; open-position gains and losses are excluded.',
        )
      }}
      {{
        tr(
          'Historical backtests do not promise a fixed monthly income. This fixed pair list differs from the paper bot’s dynamic pair selection; no extra slippage is simulated.',
        )
      }}
    </p>
  </section>
</template>
<style scoped>
.report-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
  padding: 24px;
}
.report-metrics span {
  display: block;
  color: var(--workspace-muted);
  font-size: 12px;
  margin-bottom: 9px;
}
.report-metrics strong {
  font-size: 19px;
  font-variant-numeric: tabular-nums;
}
.monthly-chart {
  height: 290px;
  width: 100%;
}
.monthly-table {
  width: 100%;
  border-collapse: collapse;
  white-space: nowrap;
  font-size: 13px;
}
.monthly-table th,
.monthly-table td {
  text-align: right;
  padding: 14px 12px;
  border-bottom: 1px solid var(--workspace-border);
}
.monthly-table th:first-child {
  text-align: left;
}
.monthly-table thead {
  color: var(--workspace-muted);
}
.monthly-table small {
  display: block;
  font-weight: 400;
}
@media (max-width: 767px) {
  .report-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .report-metrics strong {
    font-size: 16px;
  }
}
</style>
