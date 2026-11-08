<script setup lang="ts">
import { tr } from '@/i18n';
import type { Trade } from '@/types';

const colorStore = useColorStore();

defineProps<{
  trade: Trade;
  stakeCurrency: string;
}>();

const { showTradeCustomData } = useTradeCustomData();
</script>

<template>
  <div class="text-start grid md:grid-cols-[repeat(auto-fit,minmax(500px,1fr))] gap-4 px-2">
    <div class="">
      <div class="flex justify-between items-center border-b">
        <h5 class="text-xl font-semibold w-full block mb-1">{{ tr('General') }}</h5>
        <UButton
          size="sm"
          variant="outline"
          color="neutral"
          @click="showTradeCustomData({ tradeId: trade.trade_id })"
          :label="tr('Show custom data')"
          icon="mdi:database-search"
        />
      </div>
      <ValuePair :description="tr('Trade Id')">{{ trade.trade_id }}</ValuePair>
      <ValuePair :description="tr('Pair')">{{ trade.pair }}</ValuePair>

      <ValuePair :description="tr('Open date')">{{ timestampms(trade.open_timestamp) }}</ValuePair>
      <ValuePair v-if="trade.enter_tag" :description="tr('Entry tag')">{{
        trade.enter_tag
      }}</ValuePair>
      <ValuePair v-if="trade.is_open" :description="tr('Stake')">
        {{ formatPriceCurrency(trade.stake_amount, stakeCurrency) }}
        <template v-if="trade.trading_mode !== 'spot'">
          ({{ trade.leverage }}x)
          <span :title="tr('Position value')" class="italic">{{
            formatPriceCurrency(trade.amount * trade.open_rate, stakeCurrency)
          }}</span>
        </template>
      </ValuePair>
      <ValuePair v-if="!trade.is_open" :description="tr('Total Stake')">
        {{ formatPriceCurrency(trade.max_stake_amount ?? trade.stake_amount, stakeCurrency) }}
        {{ trade.trading_mode !== 'spot' ? `(${trade.leverage}x)` : '' }}
      </ValuePair>
      <ValuePair :description="tr('Amount')">{{ formatPrice(trade.amount) }}</ValuePair>
      <ValuePair :description="tr('Open Rate')">{{ formatPrice(trade.open_rate) }}</ValuePair>
      <ValuePair v-if="trade.is_open && trade.current_rate" :description="tr('Current Rate')">
        {{ formatPrice(trade.current_rate) }}
        <span :title="tr('Current Value - In futures mode Collateral + PnL')" class="italic">
          ({{ formatPriceCurrency(trade.stake_amount + (trade.profit_abs ?? 0), stakeCurrency) }})
        </span>
      </ValuePair>
      <ValuePair v-if="!trade.is_open && trade.close_rate" :description="tr('Close Rate')">{{
        formatPrice(trade.close_rate)
      }}</ValuePair>

      <ValuePair v-if="trade.close_timestamp" :description="tr('Close date')">{{
        timestampms(trade.close_timestamp)
      }}</ValuePair>
      <ValuePair
        v-if="trade.is_open && trade.realized_profit && !trade.total_profit_abs"
        :description="tr('Realized Profit')"
      >
        <TradeProfit :trade="trade" mode="realized" />
      </ValuePair>
      <ValuePair v-if="trade.is_open && trade.total_profit_abs" :description="tr('Total Profit')">
        <TradeProfit :trade="trade" mode="total" />
      </ValuePair>
      <ValuePair
        v-if="trade.profit_ratio && trade.profit_abs"
        :description="`${trade.is_open ? tr('Current Profit') : tr('Close Profit')}`"
      >
        <TradeProfit :trade="trade" />
      </ValuePair>
      <BaseCollapsible :title="tr('Details')" class="px-2 pb-2">
        <ValuePair v-if="trade.min_rate" :description="tr('Min Rate')">{{
          formatPrice(trade.min_rate)
        }}</ValuePair>
        <ValuePair v-if="trade.max_rate" :description="tr('Max Rate')">{{
          formatPrice(trade.max_rate)
        }}</ValuePair>
        <ValuePair :description="tr('Open-Fees')">
          {{ trade.fee_open_cost }} {{ trade.quote_currency }}
          <span v-if="trade.quote_currency !== trade.fee_open_currency">
            {{ tr('(in') }} {{ trade.fee_open_currency }})
          </span>
          ({{ formatPercent(trade.fee_open) }})
        </ValuePair>
        <ValuePair v-if="trade.fee_close_cost && trade.fee_close" :description="tr('Fees close')">
          {{ trade.fee_close_cost }} {{ trade.fee_close_currency }} ({{
            formatPercent(trade.fee_close)
          }})
        </ValuePair>
      </BaseCollapsible>
    </div>
    <div class="mt-2 lg:mt-0">
      <h5 class="text-xl font-semibold border-b pb-1 w-full block mb-1">{{ tr('Stoploss') }}</h5>
      <ValuePair :description="tr('Stoploss')">
        {{ formatPercent(trade.stop_loss_ratio) }} |
        {{ formatPrice(trade.stop_loss_abs) }}
      </ValuePair>
      <ValuePair
        :description="tr('At risk')"
        help="The amount at risk based on the stake amount. This is how much you would lose if the stoploss is hit."
      >
        {{
          formatPriceCurrency(trade.stake_amount * Math.abs(trade.stop_loss_ratio), stakeCurrency)
        }}
      </ValuePair>
      <ValuePair
        v-if="trade.is_open && trade.stoploss_current_dist_ratio && trade.stoploss_current_dist"
        :description="tr('Current stoploss dist')"
      >
        {{ formatPercent(trade.stoploss_current_dist_ratio) }} |
        {{ formatPrice(trade.stoploss_current_dist) }}
      </ValuePair>
      <ValuePair
        v-if="trade.initial_stop_loss_pct && trade.initial_stop_loss_abs"
        :description="tr('Initial Stoploss')"
      >
        {{ formatPercent(trade.initial_stop_loss_pct / 100) }} |
        {{ formatPrice(trade.initial_stop_loss_abs) }}
      </ValuePair>
      <ValuePair
        v-if="trade.stoploss_last_update_timestamp"
        :description="tr('Stoploss last updated')"
      >
        {{ timestampms(trade.stoploss_last_update_timestamp) }}
      </ValuePair>
      <div v-if="trade.trading_mode !== undefined && trade.trading_mode !== 'spot'">
        <h5 class="text-xl font-semibold border-b pb-1 w-full block mb-1">
          {{ tr('Futures/Margin') }}
        </h5>
        <ValuePair :description="tr('Direction')">
          {{ trade.is_short ? tr('short') : tr('long') }} - {{ trade.leverage }}x
        </ValuePair>
        <ValuePair
          v-if="trade.funding_fees !== undefined"
          :description="tr('Funding fees')"
          help="Positive funding_fees -> Trade has gained from fees. Negative funding_fees -> Trade had to pay the fees."
        >
          {{ formatDecimal(trade.funding_fees) }}
        </ValuePair>
        <ValuePair v-if="trade.interest_rate !== undefined" :description="tr('Interest rate')">
          {{ formatDecimal(trade.interest_rate) }}
        </ValuePair>
        <ValuePair
          v-if="trade.liquidation_price !== undefined"
          :description="tr('Liquidation Price')"
        >
          {{ formatPrice(trade.liquidation_price) }}
        </ValuePair>
      </div>
      <BaseCollapsible
        v-if="trade.orders"
        :title="tr('Orders {0}', { 0: trade.orders.length > 1 ? `[${trade.orders.length}]` : '' })"
        class="px-2 pb-2"
      >
        <div
          v-for="(order, key) in trade.orders"
          :key="key"
          class="flex items-center gap-1 2"
          :title="
            tr('{0} {1} order for {2} at {3}, filled {4}', {
              0: order.ft_order_side,
              1: order.order_type,
              2: formatPriceCurrency(order.amount, trade.base_currency ?? ''),
              3: formatPriceCurrency(order.safe_price, trade.quote_currency ?? ''),
              4: formatPrice(order.filled),
            })
          "
        >
          (#{{ key + 1 }})
          <i-mdi-triangle
            v-if="order.ft_order_side === 'buy'"
            class="me-1"
            :style="{
              color: colorStore.colorUp,
            }"
            style="font-size: 0.6rem"
          />
          <i-mdi-triangle-down
            v-else
            class="me-1"
            :style="{ color: colorStore.colorDown }"
            style="font-size: 0.6rem"
          />
          <DateTimeTZ v-if="order.order_timestamp" :date="order.order_timestamp" show-timezone />
          <b
            class="ms-1"
            :style="{
              color: order.ft_order_side === 'buy' ? colorStore.colorUp : colorStore.colorDown,
            }"
            >{{ order.ft_order_side }}</b
          >
          {{ tr('for') }} <b>{{ formatPrice(order.safe_price) }}</b> |
          <span v-if="order.remaining && order.remaining !== 0" :title="tr('remaining')"
            >{{ formatPrice(order.remaining, 8) }} /
          </span>
          <span :title="tr('Filled')">{{ formatPrice(order.filled ?? 0, 8) }}</span>
          <template v-if="order.ft_order_tag"> | {{ order.ft_order_tag ?? '' }}</template>
        </div>
      </BaseCollapsible>
    </div>
  </div>
</template>
