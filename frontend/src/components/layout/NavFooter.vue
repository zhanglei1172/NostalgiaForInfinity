<script setup lang="ts">
import { tr } from '@/i18n';
const botStore = useBotStore();
</script>
<template>
  <nav
    v-if="botStore.hasBots && !botStore.canRunBacktest"
    class="mobile-dock"
    :aria-label="tr('Quick navigation')"
  >
    <RouterLink
      v-for="item in [
        { to: '/dashboard', label: tr('Dashboard'), icon: 'i-mdi-view-dashboard-outline' },
        { to: '/trade', label: tr('Trade'), icon: 'i-mdi-swap-horizontal' },
        { to: '/trade_history', label: tr('History'), icon: 'i-mdi-history' },
        { to: '/balance', label: tr('Balance'), icon: 'i-mdi-wallet-outline' },
      ]"
      :key="item.to"
      :to="item.to"
      ><UIcon :name="item.icon" class="size-5" /><span>{{ item.label }}</span></RouterLink
    >
  </nav>
</template>
