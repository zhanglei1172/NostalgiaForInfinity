<script setup lang="ts">
import { tr } from '@/i18n';
import { recordAuthFreeze, useAuthFreeze } from '@/composables/authFreeze';
const route = useRoute();
const bots = useBotStore();
const freeze = useAuthFreeze(() => bots.activeBot?.getLoginInfo().apiUrl ?? window.location.origin);
watch(
  () => bots.selectedBot,
  async (id) => {
    const target = bots.activeBot?.getLoginInfo().apiUrl;
    if (!id || !target) return;
    try {
      const data = await useApi(useLoginInfo(id), id).api<{
        password_protection?: { retry_after: number };
      }>('/account');
      const seconds = data.password_protection?.retry_after ?? 0;
      if (seconds > 0)
        recordAuthFreeze(target, { detail: 'account_rate_limited', retry_after: seconds });
    } catch {
      // Older bots may not implement account protection; their normal login flow still applies.
    }
  },
  { immediate: true },
);
const content = useTemplateRef('content');
const titles = computed<Record<string, string>>(() => ({
  '/balance': tr('Balance'),
  '/trade_history': tr('History'),
  '/open_trades': tr('Open Trades'),
  '/pairlist': tr('Pairlist'),
  '/graph': tr('Chart'),
  '/download_data': tr('Download Data'),
  '/pairlist_config': tr('Pairlist Config'),
  '/recursive_analysis': tr('Recursive Analysis'),
  '/lookahead_analysis': tr('Lookahead Analysis'),
}));
watch(
  () => route.path,
  () => {
    content.value?.scrollTo({ top: 0 });
  },
);
</script>
<template>
  <main id="main-content" ref="content" tabindex="-1" class="workspace-main">
    <div
      v-if="freeze.remaining && !['/login', '/setup'].includes(route.path)"
      class="workspace-page pb-0"
    >
      <UAlert role="alert" color="warning" :title="freeze.message" />
    </div>
    <div v-if="titles[route.path]" class="workspace-page feature-page">
      <div class="page-heading">
        <div>
          <p class="eyebrow">{{ tr('WORKSPACE TOOLS') }}</p>
          <h1>{{ titles[route.path] }}</h1>
        </div>
      </div>
      <div class="feature-content"><RouterView /></div>
    </div>
    <RouterView v-else />
  </main>
</template>
<style scoped>
.feature-page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}
.feature-content {
  flex: 1;
  min-height: 500px;
}
.feature-page:has(.echarts) {
  height: 100%;
}
</style>
