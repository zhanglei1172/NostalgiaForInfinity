<script setup lang="ts">
import { tr } from '@/i18n';
import type { Trade } from '@/types';
defineProps<{ tradeId: Trade['trade_id'] }>();
defineEmits<{
  close: [value: boolean];
}>();
</script>

<template>
  <UModal :title="tr('Custom data for trade {0}', { 0: tradeId })" description="">
    <template #body>
      <TradeCustomData :trade-id="tradeId" />
    </template>
  </UModal>
</template>
