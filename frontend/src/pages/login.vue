<script setup lang="ts">
import { tr } from '@/i18n';
const route = useRoute();
const router = useRouter();
onMounted(async () => {
  try {
    const response = await fetch('/api/v1/live/setup-status', { cache: 'no-store' });
    if (response.ok && (await response.json()).required === true) await router.replace('/setup');
  } catch {
    /* Standard bots do not expose live setup. */
  }
});
const botStore = useBotStore();
const existingAuth = computed(() =>
  typeof route.query.botId === 'string'
    ? botStore.botStores[route.query.botId]?.getLoginInfo()
    : undefined,
);
const loginInfo = computed(() =>
  existingAuth.value && typeof route.query.botId === 'string'
    ? { ...existingAuth.value, botId: route.query.botId }
    : undefined,
);
const notice = computed(() => {
  switch (route.query.reason) {
    case 'setup-complete':
      return tr('Administrator created. Sign in to configure the trading account.');
    case 'password-changed':
      return tr('Password updated. Sign in with your new password.');
    case 'sessions-revoked':
      return tr('All devices have been signed out. Sign in again to continue.');
    case 'signed-out':
      return tr('You have signed out of this device.');
    case 'session-expired':
      return tr('Your login has expired. Please sign in again.');
    default:
      return '';
  }
});
definePage({ meta: { allowAnonymous: true } });
</script>
<template>
  <div class="login-page">
    <div class="login-story">
      <span class="brand-symbol">∞</span>
      <p class="eyebrow mt-8">NOSTALGIA FOR INFINITY</p>
      <h1>{{ tr('A clearer view of every trade.') }}</h1>
      <p>
        {{
          tr(
            'Monitor your capital, understand performance, and manage your strategy in one workspace.',
          )
        }}
      </p>
      <div class="login-features">
        <span><UIcon name="i-mdi-chart-line" />{{ tr('Equity at a glance') }}</span
        ><span><UIcon name="i-mdi-shield-check-outline" />{{ tr('Paper & live accounts') }}</span
        ><span><UIcon name="i-mdi-translate" />{{ tr('Chinese & English') }}</span>
      </div>
    </div>
    <section class="workspace-panel login-form">
      <p class="eyebrow">{{ tr('CONNECT YOUR BOT') }}</p>
      <h2>{{ tr('Welcome back') }}</h2>
      <p class="muted mb-7 text-sm">{{ tr('Sign in with your bot API credentials.') }}</p>
      <UAlert v-if="notice" :title="notice" class="mb-6" color="info" />
      <BotLogin :existing-auth="loginInfo" />
      <p class="muted text-xs mt-6 leading-relaxed">
        {{ tr('For a local Docker installation, keep the API URL set to this page’s address.') }}
      </p>
    </section>
  </div>
</template>
<style scoped>
.login-page {
  min-height: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 440px);
  align-items: center;
  gap: 70px;
  max-width: 1150px;
  margin: auto;
  padding: 50px;
}
.login-story h1 {
  font-size: clamp(30px, 3vw, 46px);
  font-weight: 680;
  letter-spacing: -0.05em;
  line-height: 1.4;
  margin: 18px 0;
}
.login-story > p:not(.eyebrow) {
  color: var(--workspace-muted);
  line-height: 1.9;
  font-size: 15px;
  max-width: 400px;
}
.login-features {
  display: flex;
  flex-direction: column;
  gap: 20px;
  color: var(--workspace-muted);
  margin-top: 36px;
  font-size: 13px;
}
.login-features span {
  display: flex;
  gap: 12px;
  align-items: center;
}
.login-form {
  padding: 32px;
}
.login-form h2 {
  font-size: 26px;
  font-weight: 650;
  margin: 12px 0;
}
@media (max-width: 1100px) {
  .login-page {
    padding: 40px 24px;
    gap: 35px;
  }
}
@media (max-width: 767px) {
  .login-page {
    grid-template-columns: minmax(0, 1fr);
    padding: 24px 16px;
    gap: 20px;
    align-content: start;
  }
  .login-story {
    display: none;
  }
  .login-form {
    padding: 24px;
    max-width: 440px;
    width: 100%;
    margin: 0 auto;
  }
}
</style>
