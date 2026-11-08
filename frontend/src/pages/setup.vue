<script setup lang="ts">
import { tr } from '@/i18n';
import { recordAuthFreeze, useAuthFreeze } from '@/composables/authFreeze';

definePage({ meta: { allowAnonymous: true } });
const router = useRouter();
const freeze = useAuthFreeze(window.location.origin, 'setup');
const required = ref<boolean>();
const username = ref('');
const password = ref('');
const confirmation = ref('');
const busy = ref(false);
const error = ref('');
const valid = computed(
  () =>
    /^[A-Za-z0-9_.-]{3,32}$/.test(username.value) &&
    password.value.length >= 12 &&
    password.value.length <= 128 &&
    password.value === confirmation.value,
);
onMounted(async () => {
  try {
    const response = await fetch('/api/v1/live/setup-status', { cache: 'no-store' });
    if (!response.ok) throw new Error();
    required.value = (await response.json()).required === true;
  } catch {
    error.value = tr(
      'The setup service is unavailable. Check that the live management service is running.',
    );
  }
});
async function submit() {
  if (!valid.value || busy.value || freeze.remaining) return;
  error.value = '';
  busy.value = true;
  try {
    const response = await fetch('/api/v1/live/setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value, password: password.value }),
    });
    if (!response.ok) {
      if (
        response.status === 429 &&
        recordAuthFreeze(
          window.location.origin,
          await response.json(),
          response.headers.get('Retry-After'),
          'setup',
        )
      )
        return;
      error.value =
        response.status === 409
          ? tr('The administrator account already exists. Sign in to continue.')
          : tr(
              'Unable to create the administrator. Use the local address and check the username and password requirements.',
            );
      return;
    }
    await router.replace({
      path: '/login',
      query: { reason: 'setup-complete', redirect: '/trading_settings' },
    });
  } catch {
    error.value = tr('The setup request failed. Refresh to check whether the account was created.');
  } finally {
    password.value = '';
    confirmation.value = '';
    busy.value = false;
  }
}
onBeforeUnmount(() => {
  password.value = '';
  confirmation.value = '';
});
</script>
<template>
  <div class="setup-page workspace-page">
    <section class="workspace-panel p-6 sm:p-8">
      <p class="eyebrow">NFI · OKX</p>
      <h1 class="text-2xl mt-3 mb-4">{{ tr('Create the administrator account') }}</h1>
      <p class="muted text-sm mb-6">
        {{
          tr(
            'Set up Web access first. Exchange credentials and the trading budget are configured after signing in. No trading starts during setup.',
          )
        }}
      </p>
      <UAlert
        v-if="freeze.remaining"
        role="alert"
        :title="freeze.message"
        color="warning"
        class="mb-5"
      />
      <UAlert v-if="error" role="alert" :title="error" color="error" class="mb-5" />
      <UAlert
        v-if="required === false"
        :title="tr('The administrator account already exists. Sign in to continue.')"
        class="mb-5"
      />
      <form v-if="required" class="space-y-5" @submit.prevent="submit">
        <UFormField
          :label="tr('Administrator username')"
          :help="tr('3–32 letters, numbers, dots, underscores or hyphens.')"
        >
          <UInput
            v-model="username"
            autocomplete="username"
            class="w-full"
            required
            :maxlength="32"
          />
        </UFormField>
        <UFormField
          :label="tr('Administrator password')"
          :help="tr('Use 12–128 characters without control characters.')"
        >
          <PasswordInput v-model="password" autocomplete="new-password" class="w-full" required />
        </UFormField>
        <UFormField :label="tr('Confirm administrator password')">
          <PasswordInput
            v-model="confirmation"
            autocomplete="new-password"
            class="w-full"
            required
          />
        </UFormField>
        <UButton type="submit" :disabled="!valid || busy || !!freeze.remaining" :loading="busy">{{
          tr('Create account and sign in')
        }}</UButton>
      </form>
      <UButton v-if="required === false" to="/login" class="mt-5">{{ tr('Login') }}</UButton>
    </section>
  </div>
</template>
<style scoped>
.setup-page {
  max-width: 600px;
  padding-top: 48px;
}
</style>
