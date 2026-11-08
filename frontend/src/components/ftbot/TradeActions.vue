<script setup lang="ts">
import { tr } from '@/i18n';
import type { Trade, BotFeatures } from '@/types';

withDefaults(
  defineProps<{
    botFeatures: BotFeatures;
    trade: Trade;
    enableForceEntry?: boolean;
  }>(),
  {
    enableForceEntry: false,
  },
);
defineEmits<{
  forceExit: [trade: Trade, type?: 'limit' | 'market'];
  forceExitPartial: [trade: Trade];
  cancelOpenOrder: [trade: Trade];
  reloadTrade: [trade: Trade];
  deleteTrade: [trade: Trade];
  forceEntry: [trade: Trade];
}>();
</script>

<template>
  <div class="flex flex-col gap-1">
    <UButton
      v-if="!botFeatures.forceExitParams"
      class="justify-start!"
      color="neutral"
      :title="tr('Forceexit')"
      :label="tr('Forceexit')"
      icon="mdi:close-box"
      @click="$emit('forceExit', trade)"
    />
    <UButton
      v-if="botFeatures.forceExitParams"
      class="justify-start!"
      color="neutral"
      :title="tr('Forceexit limit')"
      :label="tr('Forceexit limit')"
      icon="mdi:close-box"
      @click="$emit('forceExit', trade, 'limit')"
    />
    <UButton
      v-if="botFeatures.forceExitParams"
      class="justify-start!"
      color="neutral"
      :title="tr('Forceexit market')"
      :label="tr('Forceexit market')"
      icon="mdi:close-box"
      @click="$emit('forceExit', trade, 'market')"
    />
    <UButton
      v-if="botFeatures.forceEntryTag"
      class="justify-start!"
      color="neutral"
      :title="tr('Forceexit partial')"
      :label="tr('Forceexit partial')"
      icon="mdi:close-box-multiple"
      @click="$emit('forceExitPartial', trade)"
    />
    <UButton
      v-if="botFeatures.cancelOpenOrders && (trade.open_order_id || trade.has_open_orders)"
      class="justify-start!"
      color="neutral"
      :title="tr('Cancel open orders')"
      :label="tr('Cancel open orders')"
      icon="mdi:cancel"
      @click="$emit('cancelOpenOrder', trade)"
    />
    <UButton
      v-if="enableForceEntry"
      class="justify-start!"
      color="neutral"
      :title="tr('Increase position')"
      :label="tr('Increase position')"
      icon="mdi:plus-box-multiple-outline"
      @click="$emit('forceEntry', trade)"
    />
    <UButton
      v-if="botFeatures.reloadTrade"
      class="justify-start!"
      color="neutral"
      :title="tr('Reload')"
      :label="tr('Reload')"
      icon="mdi:reload-alert"
      @click="$emit('reloadTrade', trade)"
    />
    <UButton
      class="justify-start!"
      color="neutral"
      :title="tr('Delete trade')"
      :label="tr('Delete trade')"
      icon="mdi:delete"
      @click="$emit('deleteTrade', trade)"
    />
  </div>
</template>
