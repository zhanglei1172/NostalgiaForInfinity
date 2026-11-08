<script setup lang="ts">
import { tr } from '@/i18n';
import { useAuthFreeze } from '@/composables/authFreeze';
interface AccountProfile {
  username: string;
  password_changed_at: string | null;
  sessions_revoked_at: string | null;
  min_password_length: number;
  max_password_length: number;
  refresh_token_days: number;
  password_protection?: {
    max_failures: number;
    window_seconds: number;
    freeze_seconds: number;
    retry_after: number;
  };
}
const botStore = useBotStore();
const freeze = useAuthFreeze(
  () => botStore.activeBot?.getLoginInfo().apiUrl ?? window.location.origin,
);
const router = useRouter();
const { confirm } = useConfirmBox();
const profile = ref<AccountProfile>();
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const unsupported = ref(false);
const currentPassword = ref('');
const newPassword = ref('');
const confirmPassword = ref('');
const revokePassword = ref('');
let requestId = 0;
const apiFor = (id: string) => useApi(useLoginInfo(id), id).api;
function clearPasswords() {
  currentPassword.value = '';
  newPassword.value = '';
  confirmPassword.value = '';
  revokePassword.value = '';
}
function errorMessage(value: unknown) {
  if (freeze.capture(value)) return '';
  const messages: Record<string, string> = {
    account_guard_unavailable: tr(
      'Password protection storage is unavailable. Verification is blocked; check storage permissions.',
    ),
    account_incorrect_password: tr('The current password is incorrect.'),
    account_invalid_password: tr('Use 12–128 characters without control characters.'),
    account_password_unchanged: tr('Choose a password different from the current password.'),
    account_rate_limited: tr('Too many incorrect attempts. Try again in 5 minutes.'),
    account_storage_unavailable: tr(
      'The password could not be saved. Your existing password is unchanged. Try again later.',
    ),
    account_invalid_request: tr('Check the password fields and try again.'),
  };
  if (isApiError(value)) {
    if (value.status === 401) return tr('Your login has expired. Please sign in again.');
    const code = value.data?.detail;
    if (typeof code === 'string' && messages[code]) return messages[code];
  }
  return tr('The request could not be completed. Check your connection and try again.');
}
async function load() {
  const sequence = ++requestId;
  const id = botStore.selectedBot;
  clearPasswords();
  error.value = '';
  unsupported.value = false;
  profile.value = undefined;
  loading.value = true;
  try {
    const data = await apiFor(id)<AccountProfile>('/account');
    if (sequence !== requestId) return;
    if (!data || typeof data.username !== 'string') unsupported.value = true;
    else {
      profile.value = data;
      freeze.restore(data.password_protection?.retry_after ?? 0);
    }
  } catch (value) {
    if (sequence !== requestId) return;
    if (isApiError(value) && [404, 405].includes(value.status ?? 0)) unsupported.value = true;
    else error.value = errorMessage(value);
  } finally {
    if (sequence === requestId) loading.value = false;
  }
}
async function finish(id: string, reason: string) {
  clearPasswords();
  const selected = botStore.selectedBot === id;
  botStore.removeBot(id);
  if (selected) await router.replace({ path: '/login', query: { redirect: '/account', reason } });
  else showAlert(tr('Account security updated. Sign in to that bot again.'));
}
async function changePassword() {
  if (saving.value || !profile.value || freeze.remaining) return;
  error.value = '';
  if (!currentPassword.value) {
    error.value = tr('Enter your current password.');
    return;
  }
  if (
    Array.from(newPassword.value).length < 12 ||
    Array.from(newPassword.value).length > 128 ||
    Array.from(newPassword.value).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)
  ) {
    error.value = tr('Use 12–128 characters without control characters.');
    return;
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = tr('The new passwords do not match.');
    return;
  }
  if (newPassword.value === currentPassword.value) {
    error.value = tr('Choose a password different from the current password.');
    return;
  }
  const id = botStore.selectedBot;
  saving.value = true;
  try {
    await apiFor(id)('/account/password', {
      method: 'POST',
      body: { current_password: currentPassword.value, new_password: newPassword.value },
    });
    await finish(id, 'password-changed');
  } catch (value) {
    error.value = errorMessage(value);
  } finally {
    saving.value = false;
  }
}
async function revokeSessions() {
  if (saving.value || !profile.value || freeze.remaining) return;
  error.value = '';
  if (!revokePassword.value) {
    error.value = tr('Enter your current password.');
    return;
  }
  const id = botStore.selectedBot;
  const current = revokePassword.value;
  if (
    !(await confirm({
      title: tr('Sign out all devices'),
      message: tr(
        'End every login for this bot, including this device? Trading will continue running.',
      ),
    }))
  )
    return;
  saving.value = true;
  try {
    await apiFor(id)('/account/sessions/revoke', {
      method: 'POST',
      body: { current_password: current },
    });
    await finish(id, 'sessions-revoked');
  } catch (value) {
    error.value = errorMessage(value);
  } finally {
    saving.value = false;
  }
}
async function signOut() {
  if (saving.value) return;
  await finish(botStore.selectedBot, 'signed-out');
}
watch(() => botStore.selectedBot, load, { immediate: true });
onBeforeUnmount(() => {
  ++requestId;
  clearPasswords();
});
</script>
<template>
  <div class="workspace-page account-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ tr('ACCOUNT SECURITY') }}</p>
        <h1>{{ tr('Account & security') }}</h1>
        <p>{{ tr('Manage the administrator login for the selected bot.') }}</p>
      </div>
      <UButton to="/trading_settings" color="neutral" icon="i-mdi-key-chain-variant">{{
        tr('Trading account')
      }}</UButton>
      <UButton color="neutral" icon="i-mdi-logout" :disabled="saving" @click="signOut">{{
        tr('Sign out this device')
      }}</UButton>
    </div>
    <UAlert v-if="error" class="mb-6" color="error" :title="error" role="alert" />
    <div v-if="loading" class="workspace-panel p-8 muted" role="status">
      {{ tr('Loading account details…') }}
    </div>
    <UAlert
      v-else-if="unsupported"
      color="warning"
      :title="tr('This bot does not support account management yet.')"
      :description="
        tr('Update this bot to the NFI image with account management, then refresh this page.')
      "
    />
    <div v-else-if="profile" class="account-grid">
      <section class="workspace-panel account-profile">
        <div class="security-symbol">
          <UIcon name="i-mdi-account-lock-outline" class="size-7" />
        </div>
        <h2 class="section-title">{{ tr('Current account') }}</h2>
        <dl>
          <div>
            <dt>{{ tr('Username') }}</dt>
            <dd>{{ profile.username }}</dd>
          </div>
          <div>
            <dt>{{ tr('Bot') }}</dt>
            <dd>{{ botStore.activeBot?.botName }}</dd>
          </div>
          <div>
            <dt>{{ tr('Password last changed') }}</dt>
            <dd>
              {{
                profile.password_changed_at
                  ? timestampms(new Date(profile.password_changed_at).getTime())
                  : tr('Not changed yet')
              }}
            </dd>
          </div>
          <div>
            <dt>{{ tr('Login duration') }}</dt>
            <dd>{{ tr('Up to {0} days', { 0: profile.refresh_token_days }) }}</dd>
          </div>
        </dl>
        <p v-if="profile.password_protection" class="muted text-sm leading-relaxed mt-6">
          {{
            tr(
              'Five failed password attempts within five minutes freeze password verification for five minutes. Login and administrator settings share this limit. Existing sessions and trading continue; restarting does not clear the freeze.',
            )
          }}
        </p>
        <p class="muted text-xs leading-relaxed mt-6">
          {{
            tr(
              'Password changes and sign-outs affect access to this bot. The trading strategy continues running.',
            )
          }}
        </p>
      </section>
      <div class="space-y-6">
        <section class="workspace-panel">
          <div class="panel-heading">
            <h2>{{ tr('Change password') }}</h2>
            <p class="muted font-normal text-xs mt-2">
              {{ tr('After saving, all devices must sign in with the new password.') }}
            </p>
          </div>
          <form class="p-6 space-y-5" novalidate @submit.prevent="changePassword">
            <UFormField :label="tr('Current password')" required
              ><PasswordInput
                id="account-current-password"
                v-model="currentPassword"
                autocomplete="current-password"
                :maxlength="1024"
                :disabled="saving"
            /></UFormField>
            <UFormField :label="tr('New password')" required :hint="tr('12–128 characters')"
              ><PasswordInput
                id="account-new-password"
                v-model="newPassword"
                autocomplete="new-password"
                :maxlength="256"
                :disabled="saving"
            /></UFormField>
            <UFormField :label="tr('Confirm new password')" required
              ><PasswordInput
                id="account-confirm-password"
                v-model="confirmPassword"
                autocomplete="new-password"
                :maxlength="256"
                :disabled="saving"
            /></UFormField>
            <div class="flex justify-end">
              <UButton
                type="submit"
                icon="i-mdi-lock-reset"
                :loading="saving"
                :disabled="!!freeze.remaining"
                variant="solid"
                >{{ tr('Save password and sign in again') }}</UButton
              >
            </div>
          </form>
        </section>
        <section class="workspace-panel">
          <div class="panel-heading">
            <h2>{{ tr('Login sessions') }}</h2>
            <p class="muted font-normal text-xs mt-2">
              {{ tr('Sign out every device if you no longer trust an existing login.') }}
            </p>
          </div>
          <form class="p-6 space-y-5" novalidate @submit.prevent="revokeSessions">
            <UFormField :label="tr('Current password')" required
              ><PasswordInput
                id="revoke-current-password"
                v-model="revokePassword"
                autocomplete="current-password"
                :maxlength="1024"
                :disabled="saving" /></UFormField
            ><UButton
              type="submit"
              color="error"
              icon="i-mdi-logout-variant"
              :loading="saving"
              :disabled="!!freeze.remaining"
              >{{ tr('Sign out all devices') }}</UButton
            >
          </form>
        </section>
      </div>
    </div>
    <UButton v-else color="neutral" icon="i-mdi-refresh" @click="load">{{ tr('Retry') }}</UButton>
  </div>
</template>
<style scoped>
.account-page {
  max-width: 1400px;
}
.account-grid {
  display: grid;
  grid-template-columns: minmax(240px, 0.75fr) minmax(0, 1.4fr);
  gap: 24px;
  align-items: start;
}
.account-profile {
  padding: 28px;
}
.security-symbol {
  padding: 15px;
  border-radius: 14px;
  background: #7794fa14;
  color: var(--workspace-accent);
  width: fit-content;
  margin-bottom: 24px;
}
dl {
  margin-top: 26px;
}
dl > div {
  margin-top: 20px;
}
dt {
  color: var(--workspace-muted);
  font-size: 12px;
  margin-bottom: 7px;
}
dd {
  font-size: 14px;
  overflow-wrap: anywhere;
}
@media (max-width: 767px) {
  .account-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .account-profile {
    padding: 24px;
  }
}
</style>
