<script setup lang="ts">
import { tr } from '@/i18n';
const botStore = useBotStore();
</script>

<template>
  <div v-if="botStore.activeBot.botState" class="p-4">
    <p class="mb-4">
      {{ tr('Running Freqtrade') }} <strong>{{ botStore.activeBot.version }}</strong>
    </p>
    <p class="mb-4">
      {{ tr('Running with') }}
      <strong>
        {{ botStore.activeBot.botState.max_open_trades }}x{{
          typeof botStore.activeBot.botState.stake_amount === 'string'
            ? tr(botStore.activeBot.botState.stake_amount)
            : botStore.activeBot.botState.stake_amount
        }}
        {{ botStore.activeBot.botState.stake_currency }}
      </strong>
      {{ tr('on') }}
      <strong class="text-nowrap"
        >{{ botStore.activeBot.botState.exchange }}
        {{ botStore.activeBot.botState.demo_trading ? tr('(Demo)') : '' }}</strong
      >
      {{ tr('in') }}
      <strong
        >{{ tr(botStore.activeBot.botState.trading_mode || 'spot') }}
        {{
          botStore.activeBot.botState.trading_mode !== 'spot'
            ? tr(botStore.activeBot.botState.margin_mode ?? '')
            : ''
        }}</strong
      >
      {{ tr('markets, with Strategy') }} <strong>{{ botStore.activeBot.botState.strategy }}</strong
      >.
    </p>
    <p v-if="'stoploss_on_exchange' in botStore.activeBot.botState" class="mb-4">
      {{ tr('Stoploss on exchange is') }}
      <strong>{{
        botStore.activeBot.botState.stoploss_on_exchange ? tr('enabled') : tr('disabled')
      }}</strong
      >.
    </p>
    <p class="mb-4">
      {{ tr('Currently') }} <strong>{{ tr(botStore.activeBot.botState.state) }}</strong
      >,
      <strong
        >{{ tr('force entry:') }}
        {{ tr(botStore.activeBot.botState.force_entry_enable ? 'enabled' : 'disabled') }}</strong
      >
    </p>
    <p>
      <strong>{{ botStore.activeBot.botState.dry_run ? tr('Dry-Run') : tr('Live') }}</strong>
    </p>
    <USeparator class="my-2" />
    <p class="mb-4" v-if="botStore.activeBot.profit">
      {{ tr('Avg Profit') }}
      {{ formatPercent(botStore.activeBot.profit.profit_all_ratio_mean) }} (&sum;
      {{ formatPercent(botStore.activeBot.profit.profit_all_ratio_sum) }}{{ tr(') in') }}
      {{ botStore.activeBot.profit.trade_count }} {{ tr('Trades, with an average duration of') }}
      {{ botStore.activeBot.profit.avg_duration }}{{ tr('. Best pair:') }}
      {{ botStore.activeBot.profit.best_pair }}.
    </p>
    <p v-if="botStore.activeBot.profit?.first_trade_timestamp" class="mb-4">
      <span v-if="botStore.activeBot.profit.bot_start_timestamp" class="block">
        {{ tr('Bot start date:') }}
        <strong>
          <DateTimeTZ :date="botStore.activeBot.profit.bot_start_timestamp" show-timezone />
        </strong>
      </span>
      <span class="block">
        {{ tr('First trade opened:') }}
        <strong>
          <DateTimeTZ :date="botStore.activeBot.profit.first_trade_timestamp" show-timezone />
        </strong>
      </span>
      <span class="block">
        {{ tr('Last trade opened:') }}
        <strong>
          <DateTimeTZ :date="botStore.activeBot.profit.latest_trade_timestamp" show-timezone />
        </strong>
      </span>
    </p>
    <p>
      <span v-if="botStore.activeBot.profit?.profit_factor" class="block">
        {{ tr('Profit factor:') }}
        {{ formatNumber(botStore.activeBot.profit?.profit_factor, 2) }}
      </span>
      <span v-if="botStore.activeBot.profit?.trading_volume" class="block mb-4">
        {{ tr('Trading volume:') }}
        {{
          formatPriceCurrency(
            botStore.activeBot.profit.trading_volume,
            botStore.activeBot.botState.stake_currency,
            botStore.activeBot.botState.stake_currency_decimals ?? 3,
          )
        }}
      </span>
    </p>
    <BaseCollapsible v-if="botStore.activeBot.strategy?.params" :title="tr('Strategy parameters')">
      <StrategyParameters :strategy="botStore.activeBot.strategy" class="m-3" />
    </BaseCollapsible>
    <USeparator class="my-5" />
    <BotProfit
      class="mx-1"
      v-if="botStore.activeBot.profitAll"
      :profit-all="botStore.activeBot.profitAll"
      :stake-currency="botStore.activeBot.botState.stake_currency ?? 'USDT'"
      :stake-currency-decimals="botStore.activeBot.botState.stake_currency_decimals ?? 3"
    />
  </div>
</template>
