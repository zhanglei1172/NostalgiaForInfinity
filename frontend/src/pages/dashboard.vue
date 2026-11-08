<script setup lang="ts">
import { tr, language } from '@/i18n';
import { TimeSummaryOptions } from '@/types';
import {
  accountMetrics,
  finiteValue,
  historyPoints,
  readObservations,
  addObservation,
  observationKey,
} from '@/utils/accountMetrics';
import type { AccountPoint } from '@/utils/accountMetrics';
const botStore = useBotStore();
const bot = computed(() => botStore.activeBot);
const router = useRouter();
watch(
  () => [bot.value?.botState.nfi_live_management, bot.value?.isWebserverMode],
  () => {
    if (bot.value?.botState.nfi_live_management && bot.value?.isWebserverMode)
      void router.replace('/trading_settings');
  },
  { immediate: true },
);
const metrics = computed(() => accountMetrics(bot.value?.balance ?? {}, bot.value?.profit));
const currency = computed(() => bot.value?.stakeCurrency ?? '');
const refreshing = ref(false);
const error = ref(false);
const lastUpdated = ref<number>();
const observations = ref<AccountPoint[]>([]);
const storageAvailable = ref(true);
const key = computed(() =>
  observationKey(
    JSON.stringify([
      botStore.selectedBotObj?.botUrl,
      botStore.selectedBot,
      currency.value,
      bot.value?.botState.dry_run,
      bot.value?.balance.starting_capital,
      bot.value?.profit?.bot_start_timestamp,
    ]),
  ),
);
watch(
  key,
  () => {
    try {
      observations.value = readObservations(localStorage.getItem(key.value));
      storageAvailable.value = true;
    } catch {
      observations.value = [];
      storageAvailable.value = false;
    }
    lastUpdated.value = undefined;
  },
  { immediate: true },
);
const money = (n: unknown, signed = false) => {
  const value = finiteValue(n);
  return value === undefined
    ? '—'
    : new Intl.NumberFormat(language.value, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
        signDisplay: signed ? 'exceptZero' : 'auto',
      }).format(value);
};
const stamp = (n: number) =>
  new Intl.DateTimeFormat(language.value, {
    timeZone: useSettingsStore().timezone,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(n);
const pnlClass = (n: number | undefined) =>
  n === undefined || n === 0 ? '' : n > 0 ? 'positive' : 'negative';
const status = computed(() => {
  if (!bot.value?.isBotOnline)
    return {
      title: tr('Bot is offline'),
      text: tr('Check the connection and logs before relying on the displayed values.'),
      icon: 'i-mdi-lan-disconnect',
      tone: 'status-warning',
    };
  if (bot.value.botState.state !== 'running')
    return {
      title: tr('Trading loop is stopped'),
      text: tr(
        'Open positions are not being managed. Review the bot controls on the trading page.',
      ),
      icon: 'i-mdi-pause-circle-outline',
      tone: 'status-warning',
    };
  if (bot.value.openTradeCount > 0)
    return {
      title: tr('Strategy is managing open positions'),
      text: tr(
        'Equity includes the current valuation of open positions. P&L changes with the market.',
      ),
      icon: 'i-mdi-pulse',
      tone: '',
    };
  return {
    title: tr('Running · no open positions'),
    text: tr(
      'The bot is connected and the trading loop is running. No open positions does not confirm that an entry signal has occurred.',
    ),
    icon: 'i-mdi-radar',
    tone: '',
  };
});
async function refresh() {
  const current = bot.value;
  if (!current || current.isWebserverMode || refreshing.value) return;
  refreshing.value = true;
  const selected = botStore.selectedBot;
  try {
    if (!current.botStatusAvailable) {
      try {
        await current.getState();
      } catch {
        error.value = true;
        return;
      }
    }
    if (current.isWebserverMode) return;
    const results = await Promise.allSettled([
      current.getBalance(),
      current.getProfit(),
      current.updateWalletChange(),
      current.getTimeSummary(TimeSummaryOptions.daily, { timescale: 30 }),
    ]);
    if (selected !== botStore.selectedBot) return;
    error.value = results.some((r) => r.status === 'rejected');
    if (results[0]?.status === 'fulfilled' && results[1]?.status === 'fulfilled') {
      const time = Date.now();
      const equity = metrics.value.equity;
      if (equity !== undefined) {
        observations.value = addObservation(observations.value, { time, value: equity });
        try {
          localStorage.setItem(key.value, JSON.stringify(observations.value));
          storageAvailable.value = true;
        } catch {
          storageAvailable.value = false;
        }
      }
      lastUpdated.value = time;
    }
  } finally {
    refreshing.value = false;
    if (selected !== botStore.selectedBot) void refresh();
  }
}
watch(
  () => botStore.selectedBot,
  async () => {
    error.value = false;
    await refresh();
  },
);
onMounted(refresh);
useIntervalFn(() => {
  if (
    botStore.globalAutoRefresh &&
    bot.value?.autoRefresh &&
    document.visibilityState === 'visible'
  )
    refresh();
}, 60000);
const daily = computed(() => bot.value?.dailyStats?.data ?? []);
const latestDaily = computed(
  () => [...daily.value].sort((a, b) => b.date.localeCompare(a.date))[0],
);
</script>
<template>
  <div class="workspace-page dashboard-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ tr('PORTFOLIO MONITOR') }}</p>
        <h1>{{ tr('Account overview') }}</h1>
        <p>
          {{ bot?.botName }} <span class="mx-2">/</span> {{ bot?.botState.strategy }}
          <span class="mx-2">/</span> {{ currency }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <UButton to="/activity" color="neutral" icon="i-mdi-text-box-search-outline">{{
          tr('Strategy activity')
        }}</UButton>
        <span v-if="!botStore.globalAutoRefresh || !bot?.autoRefresh" class="muted text-xs">{{
          tr('Auto refresh paused')
        }}</span
        ><span class="muted text-xs" role="status">{{
          lastUpdated ? tr('Updated at {0}', { 0: stamp(lastUpdated) }) : tr('Waiting for data')
        }}</span
        ><UButton icon="i-mdi-refresh" color="neutral" :loading="refreshing" @click="refresh">{{
          tr('Refresh')
        }}</UButton>
      </div>
    </div>
    <UAlert
      v-if="error"
      color="warning"
      class="mb-5"
      :title="tr('Some account data could not be refreshed')"
      :description="tr('Displayed values may be stale. Check the connection and refresh to retry.')"
    />
    <div class="stat-grid">
      <article class="workspace-panel stat-card">
        <div class="stat-label">
          {{ tr('Current account equity') }}<UIcon name="i-mdi-wallet-outline" class="size-4" />
        </div>
        <div class="stat-value financial-value" data-testid="equity-value">
          {{ money(metrics.equity) }}<small>{{ currency }}</small>
        </div>
        <p class="stat-footnote">{{ tr('Includes current position valuations') }}</p>
      </article>
      <article class="workspace-panel stat-card">
        <div class="stat-label">
          {{ tr('Change from initial capital') }}<UIcon name="i-mdi-trending-up" class="size-4" />
        </div>
        <div class="stat-value financial-value" :class="pnlClass(metrics.totalProfit)">
          {{ money(metrics.totalProfit, true) }}<small>{{ currency }}</small>
        </div>
        <p class="stat-footnote">
          <span :class="pnlClass(metrics.changePercent)"
            >{{ money(metrics.changePercent, true) }}%</span
          >
          · {{ tr('Initial') }} {{ money(metrics.initial) }}
        </p>
      </article>
      <article class="workspace-panel stat-card">
        <div class="stat-label">
          {{ tr('Realized P&L') }}<UIcon name="i-mdi-check-circle-outline" class="size-4" />
        </div>
        <div class="stat-value financial-value" :class="pnlClass(metrics.realized)">
          {{ money(metrics.realized, true) }}<small>{{ currency }}</small>
        </div>
        <p class="stat-footnote">
          {{ tr('{0} closed trades', { 0: bot?.profit?.closed_trade_count ?? '—' }) }}
        </p>
      </article>
      <article class="workspace-panel stat-card">
        <div class="stat-label">
          {{ tr('Open-position P&L') }}<UIcon name="i-mdi-pulse" class="size-4" />
        </div>
        <div class="stat-value financial-value" :class="pnlClass(metrics.unrealized)">
          {{ money(metrics.unrealized, true) }}<small>{{ currency }}</small>
        </div>
        <p class="stat-footnote">
          {{ tr('{0} open positions', { 0: bot?.openTradeCount ?? '—' }) }} ·
          {{ tr('Trade P&L basis') }}
        </p>
      </article>
    </div>
    <AccountEquityChart
      :history="historyPoints(bot?.balanceHistory)"
      :observations="observations"
      :capture-start="bot?.balanceHistory?.capture_start_ts"
      :initial="metrics.initial"
      :currency="currency"
      :loading="refreshing"
      :history-error="bot?.balanceHistoryError ?? false"
      :storage-available="storageAvailable"
    />
    <div class="dashboard-secondary">
      <section class="workspace-panel bot-insight" :class="status.tone">
        <div class="insight-icon"><UIcon :name="status.icon" class="size-6" /></div>
        <div>
          <p class="eyebrow">{{ tr('BOT STATUS') }}</p>
          <h2 class="section-title">{{ status.title }}</h2>
          <p>{{ status.text }}</p>
          <UButton to="/trade" variant="link" class="px-0 mt-3" trailing-icon="i-mdi-arrow-right">{{
            tr('Open trading workspace')
          }}</UButton>
        </div>
      </section>
      <section class="workspace-panel session-summary">
        <h2 class="section-title">{{ tr('Trading summary') }}</h2>
        <dl>
          <div>
            <dt>{{ tr('Win rate') }}</dt>
            <dd>{{ money(metrics.winRate) }}%</dd>
          </div>
          <div>
            <dt>{{ tr('Latest daily realized P&L') }}</dt>
            <dd :class="pnlClass(latestDaily?.abs_profit)">
              {{ money(latestDaily?.abs_profit, true) }} {{ currency }}
            </dd>
          </div>
          <div>
            <dt>{{ tr('Daily record date') }}</dt>
            <dd>{{ latestDaily?.date ?? '—' }}</dd>
          </div>
        </dl>
      </section>
    </div>
    <p class="muted text-xs mb-6 leading-relaxed">
      {{
        tr(
          'Account change includes deposits and withdrawals; it is not a deposit-adjusted trading return. Metrics and charts refer to the selected bot only.',
        )
      }}
    </p>
    <section class="workspace-panel mb-6">
      <div class="panel-heading flex justify-between">
        <h2>{{ tr('Open Trades') }}</h2>
        <UButton to="/trade" variant="link" size="xs" trailing-icon="i-mdi-arrow-right">{{
          tr('Manage positions')
        }}</UButton>
      </div>
      <div class="dashboard-table">
        <TradeList
          active-trades
          :trades="bot?.openTrades ?? []"
          :empty-text="tr('Currently no open trades.')"
        />
      </div>
    </section>
    <div class="dashboard-secondary">
      <section class="workspace-panel">
        <div class="panel-heading">{{ tr('Daily realized P&L') }}</div>
        <div class="daily-list">
          <div v-if="!daily.length" class="muted p-6 text-center">
            {{ tr('No daily records available') }}
          </div>
          <div
            v-for="day in [...daily].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 7)"
            :key="day.date"
            class="daily-row"
          >
            <span>{{ day.date }}</span
            ><span class="muted">{{ tr('{0} closed trades', { 0: day.trade_count }) }}</span
            ><strong :class="pnlClass(day.abs_profit)"
              >{{ money(day.abs_profit, true) }} {{ currency }}</strong
            >
          </div>
        </div>
      </section>
      <section class="workspace-panel">
        <div class="panel-heading">{{ tr('Explore account') }}</div>
        <div class="account-links">
          <UButton
            to="/balance"
            color="neutral"
            variant="ghost"
            icon="i-mdi-wallet-outline"
            trailing-icon="i-mdi-arrow-top-right"
            >{{ tr('Balance') }}</UButton
          ><UButton
            to="/trade_history"
            color="neutral"
            variant="ghost"
            icon="i-mdi-history"
            trailing-icon="i-mdi-arrow-top-right"
            >{{ tr('History') }}</UButton
          ><UButton
            to="/logs"
            color="neutral"
            variant="ghost"
            icon="i-mdi-console-line"
            trailing-icon="i-mdi-arrow-top-right"
            >{{ tr('Logs') }}</UButton
          >
        </div>
      </section>
    </div>
    <section v-if="botStore.botCount > 1" class="workspace-panel">
      <div class="panel-heading">{{ tr('Bot comparison') }}</div>
      <BotComparisonList />
    </section>
    <details class="workspace-panel advanced-analytics">
      <summary>{{ tr('More analytics') }}</summary>
      <div class="analytics-grid">
        <div>
          <h2 class="section-title">{{ tr('Cumulative Profit') }}</h2>
          <CumProfitChart
            :trades="bot?.trades ?? []"
            :open-trades="bot?.openTrades ?? []"
            :show-title="false"
          />
        </div>
        <div>
          <h2 class="section-title">{{ tr('Profit Distribution') }}</h2>
          <ProfitDistributionChart :trades="bot?.trades ?? []" :show-title="false" />
        </div>
        <div>
          <h2 class="section-title">{{ tr('Trades Log') }}</h2>
          <TradesLogChart :trades="bot?.trades ?? []" :show-title="false" />
        </div>
      </div>
    </details>
  </div>
</template>
<style scoped>
.bot-insight {
  display: flex;
  align-items: flex-start;
  gap: 18px;
  padding: 25px;
}
.insight-icon {
  border-radius: 13px;
  background: #4edfc212;
  color: #20b798;
  padding: 13px;
  flex-shrink: 0;
}
.bot-insight p:not(.eyebrow) {
  font-size: 12px;
  line-height: 1.9;
  margin-top: 10px;
  color: var(--workspace-muted);
}
.status-warning .insight-icon {
  color: #d69531;
  background: #d6953112;
}
.session-summary {
  padding: 24px;
}
dl {
  margin-top: 16px;
}
dl > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  margin-top: 14px;
}
dt {
  color: var(--workspace-muted);
}
dd {
  font-weight: 550;
}
.daily-list {
  padding: 0 20px;
}
.daily-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--workspace-border);
  padding: 16px 0;
  font-size: 12px;
}
.daily-row:last-child {
  border: 0;
}
.account-links {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
}
.account-links :deep(button),
.account-links :deep(a) {
  justify-content: space-between;
  padding: 14px;
}
.advanced-analytics {
  margin: 22px 0;
}
.advanced-analytics summary {
  padding: 20px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
}
.analytics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  padding: 20px;
}
.analytics-grid > div {
  height: 320px;
  padding-bottom: 30px;
}
@media (max-width: 767px) {
  .bot-insight {
    padding: 20px 16px;
    gap: 12px;
  }
  .insight-icon {
    padding: 9px;
  }
  .analytics-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .daily-row {
    font-size: 11px;
    gap: 6px;
  }
}
</style>
