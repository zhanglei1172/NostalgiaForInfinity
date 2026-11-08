<script setup lang="ts">
import { en, zh_cn } from '@nuxt/ui/locale';
import { language } from '@/i18n';

const uiLanguage = computed(() => (language.value === 'zh-CN' ? zh_cn : en));
watch(
  language,
  (value) => {
    document.documentElement.lang = value;
  },
  { immediate: true },
);
const botStore = useBotStore();
const router = useRouter();
watch(
  () => botStore.activeBot?.isBotLoggedIn,
  (loggedIn) => {
    if (loggedIn === false && router.currentRoute.value.path !== '/login') {
      router.replace({
        path: '/login',
        query: {
          botId: botStore.selectedBot,
          reason: 'session-expired',
          redirect: router.currentRoute.value.fullPath,
        },
      });
    }
  },
);
const settingsStore = useSettingsStore();
const colorStore = useColorStore();
onMounted(() => {
  setTimezone(settingsStore.timezone);
  colorStore.updateProfitLossColor();
});
watch(
  () => settingsStore.timezone,
  (tz) => {
    console.log('timezone changed', tz);
    setTimezone(tz);
  },
);
</script>

<template>
  <UApp :locale="uiLanguage">
    <div :key="language" id="app" class="flex flex-col h-dvh" :style="colorStore.cssVars">
      <NavBar />
      <BodyLayout />
      <NavFooter />
    </div>
  </UApp>
</template>
