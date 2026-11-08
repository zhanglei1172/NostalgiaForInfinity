<script setup lang="ts">
import { tr } from '@/i18n';
import Favico from 'favico.js';
import type { NavigationMenuItem, DropdownMenuItem } from '@nuxt/ui';
const botStore = useBotStore();
const settings = useSettingsStore();
const route = useRoute();
const router = useRouter();
const loginDialog = useLoginDialog();
const menuOpen = ref(false);
const liveManagement = computed(() => botStore.activeBot?.botState.nfi_live_management === true);
let favicon: Favico | undefined;
function updateFavicon() {
  favicon ??= new Favico({ animation: 'none' });
  const count = botStore.activeBot?.openTradeCount ?? 0;
  if (settings.openTradesInTitle === OpenTradeVizOptions.showPill && count) favicon.badge(count);
  else favicon.reset();
}
watch(() => [botStore.activeBot?.openTradeCount, settings.openTradesInTitle], updateFavicon);

const items = computed<NavigationMenuItem[]>(() => [
  ...(!botStore.canRunBacktest
    ? [
        { label: tr('Dashboard'), to: '/dashboard', icon: 'i-mdi-view-dashboard-outline' },
        { label: tr('Trade'), to: '/trade', icon: 'i-mdi-swap-horizontal' },
        { label: tr('History'), to: '/trade_history', icon: 'i-mdi-history' },
        { label: tr('Strategy activity'), to: '/activity', icon: 'i-mdi-text-box-search-outline' },
        { label: tr('Balance'), to: '/balance', icon: 'i-mdi-wallet-outline' },
      ]
    : []),
  { label: tr('Backtesting'), to: '/backtest', icon: 'i-mdi-flask-outline' },
  { label: tr('Strategy library'), to: '/strategies', icon: 'i-mdi-code-braces' },
  ...(!botStore.canRunBacktest || liveManagement.value
    ? [{ label: tr('Recipe settings'), to: '/recipes', icon: 'i-mdi-tune-variant' }]
    : []),
  { label: tr('Chart'), to: '/graph', icon: 'i-mdi-chart-line' },
  ...(botStore.isWebserverMode && !liveManagement.value
    ? [
        ...(botStore.activeBot?.botFeatures.recursiveAnalysis
          ? [
              {
                label: tr('Recursive Analysis'),
                to: '/recursive_analysis',
                icon: 'i-mdi-magnify-scan',
              },
            ]
          : []),
        ...(botStore.activeBot?.botFeatures.lookaheadAnalysis
          ? [
              {
                label: tr('Lookahead Analysis'),
                to: '/lookahead_analysis',
                icon: 'i-mdi-chart-timeline-variant-shimmer',
              },
            ]
          : []),
        ...(botStore.activeBot?.botFeatures.downloadDataView
          ? [{ label: tr('Download Data'), to: '/download_data', icon: 'i-mdi-download' }]
          : []),
        ...(botStore.activeBot?.botFeatures.pairlistConfig
          ? [
              {
                label: tr('Pairlist Config'),
                to: '/pairlist_config',
                icon: 'i-mdi-format-list-numbered',
              },
            ]
          : []),
      ]
    : []),
  { label: tr('Logs'), to: '/logs', icon: 'i-mdi-console-line' },
  { label: tr('Trading account'), to: '/trading_settings', icon: 'i-mdi-key-chain-variant' },
  { label: tr('Account & security'), to: '/account', icon: 'i-mdi-account-lock-outline' },
  { label: tr('Settings'), to: '/settings', icon: 'i-mdi-cog-outline' },
]);
const accountItems = computed<DropdownMenuItem[][]>(() => [
  [
    {
      label: tr('Account & security'),
      icon: 'i-mdi-account-lock-outline',
      onSelect: () => router.push('/account'),
    },
    { label: tr('Connections'), icon: 'i-mdi-lan-connect', onSelect: () => router.push('/') },
    { label: tr('Add bot'), icon: 'i-mdi-plus', onSelect: () => loginDialog({}) },
    { label: tr('Settings'), icon: 'i-mdi-cog-outline', onSelect: () => router.push('/settings') },
    {
      label: tr('Logout'),
      icon: 'i-mdi-logout',
      onSelect: async () => {
        botStore.removeBot(botStore.selectedBot);
        await router.push('/');
      },
    },
  ],
  [{ label: settings.uiVersion, disabled: true }],
]);
const pageTitle = computed(() =>
  route.path === '/login'
    ? tr('Login')
    : route.path === '/'
      ? tr('Connections')
      : (items.value.find((i) => i.to === route.path)?.label ?? tr('Trading workspace')),
);
watch(
  () => route.path,
  () => {
    menuOpen.value = false;
  },
);
watch(
  () => [
    botStore.activeBot?.botName,
    botStore.activeBot?.openTradeCount,
    pageTitle.value,
    settings.openTradesInTitle,
  ],
  () => {
    const count =
      settings.openTradesInTitle === OpenTradeVizOptions.asTitle
        ? `(${botStore.activeBot?.openTradeCount ?? 0}) `
        : '';
    document.title = `${count}${pageTitle.value} · NFI`;
  },
  { immediate: true },
);
onMounted(() => {
  settings.loadUIVersion();
  updateFavicon();
});
const { pause } = useIntervalFn(() => botStore.pingAll(), 60000);
onBeforeUnmount(() => {
  pause();
  favicon?.reset();
});
</script>

<template>
  <a href="#main-content" class="skip-link">{{ tr('Skip to content') }}</a>
  <aside class="workspace-sidebar" :aria-label="tr('Main navigation')">
    <RouterLink to="/dashboard" class="workspace-brand">
      <span class="brand-symbol">∞</span><span>NFI <small>TRADING WORKSPACE</small></span>
    </RouterLink>
    <span class="nav-eyebrow">{{ tr('Workspace') }}</span>
    <UNavigationMenu
      orientation="vertical"
      :items="items"
      :ui="{ link: 'workspace-nav-link', list: 'space-y-1' }"
    />
    <div class="sidebar-bottom">
      <div class="sidebar-note">
        <UIcon name="i-mdi-shield-check-outline" class="size-5" />
        <div>{{ tr('Strategy automation') }}<small>NostalgiaForInfinity</small></div>
      </div>
      <RouterLink to="/" class="connection-link"
        ><UIcon name="i-mdi-lan-connect" />{{ tr('Manage connections')
        }}<UIcon name="i-mdi-arrow-top-right"
      /></RouterLink>
    </div>
  </aside>
  <header class="workspace-topbar">
    <div class="flex min-w-0 items-center gap-3">
      <USlideover v-model:open="menuOpen" :title="tr('Main navigation')">
        <UButton
          class="lg:hidden"
          icon="i-mdi-menu"
          variant="ghost"
          color="neutral"
          :aria-label="tr('Open navigation')"
        />
        <template #body
          ><UNavigationMenu orientation="vertical" :items="items" /><UButton
            to="/"
            class="mt-6"
            @click="menuOpen = false"
            >{{ tr('Manage connections') }}</UButton
          ></template
        >
      </USlideover>
      <span class="topbar-title">{{ pageTitle }}</span>
      <span
        v-if="botStore.activeBot?.botStatusAvailable"
        class="mode-badge"
        :class="{ 'mode-live': !botStore.activeBot.botState.dry_run }"
        >{{
          liveManagement && !botStore.activeBot.botState.nfi_live_configured
            ? tr('Awaiting account configuration')
            : botStore.activeBot.botState.dry_run
              ? tr('Paper trading')
              : tr('Live trading')
        }}</span
      >
    </div>
    <div class="flex items-center gap-2 sm:gap-3">
      <span v-if="botStore.hasBots" class="topbar-bot hidden xl:flex"
        ><span class="status-dot" :class="{ offline: !botStore.activeBot?.isBotOnline }" />{{
          botStore.activeBot?.botName
        }}</span
      >
      <UIcon
        v-if="!settings.confirmDialog"
        name="i-mdi-alert-outline"
        class="text-amber-500 size-5"
        :title="
          tr('Confirm dialog deactivated, Forced exits will be executed immediately. Be careful.')
        "
      />
      <BotSelect v-if="botStore.botCount > 1" />
      <LanguageSelect />
      <ThemeSelect />
      <ReloadControl v-if="botStore.hasBots" class="hidden sm:flex" />
      <UDropdownMenu v-if="botStore.hasBots" :items="accountItems"
        ><UButton
          icon="i-mdi-account-circle-outline"
          color="neutral"
          variant="ghost"
          :aria-label="tr('Account menu')"
      /></UDropdownMenu>
    </div>
  </header>
</template>
