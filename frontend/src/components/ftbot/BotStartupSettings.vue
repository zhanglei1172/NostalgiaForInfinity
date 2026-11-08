<script setup lang="ts">
import { tr } from '@/i18n';
import { useAuthFreeze } from '@/composables/authFreeze';
import type { StartupSettings } from '@/types/startup';

const bots = useBotStore();
const freeze = useAuthFreeze(() => bots.activeBot?.getLoginInfo().apiUrl ?? window.location.origin);
const { confirm } = useConfirmBox();
const settings = ref<StartupSettings>();
const autoStart = ref(false);
const password = ref('');
const loading = ref(false);
const saving = ref(false);
const unsupported = ref(false);
const error = ref('');
const notice = ref('');
let generation = 0;
const changed = computed(() => settings.value && autoStart.value !== settings.value.auto_start);
const apiFor = (id: string) => useApi(useLoginInfo(id), id).api;
function failure(value: unknown) {
  if (freeze.capture(value)) return '';
  const messages: Record<string, string> = {
    startup_origin_rejected:
      "The request origin was rejected. Open this bot's own Web address or check the reverse-proxy forwarding settings.",
    account_guard_unavailable:
      'Password protection storage is unavailable. Verification is blocked; check storage permissions.',
    account_incorrect_password: 'The current password is incorrect.',
    account_rate_limited: 'Too many incorrect attempts. Try again in 5 minutes.',
    startup_revision_conflict: 'Startup settings changed in another session. Reload before saving.',
    startup_storage_unavailable:
      'Startup settings could not be read or saved. Check storage permissions and retry.',
    startup_live_not_ready:
      'Configure and successfully load the live trading account before enabling automatic startup.',
    account_invalid_request: 'Check the startup settings and try again.',
  };
  if (isApiError(value) && typeof value.data?.detail === 'string')
    return tr(
      messages[value.data.detail] ?? 'Unable to update startup settings. Refresh and try again.',
    );
  return tr('Unable to update startup settings. Refresh and try again.');
}
async function load() {
  const sequence = ++generation;
  const id = bots.selectedBot;
  password.value = '';
  error.value = '';
  notice.value = '';
  settings.value = undefined;
  unsupported.value = false;
  loading.value = true;
  saving.value = false;
  try {
    if (!bots.hasBots) return;
    const data = await apiFor(id)<StartupSettings>('/startup-settings');
    if (sequence !== generation) return;
    if (typeof data.auto_start !== 'boolean') unsupported.value = true;
    else {
      settings.value = data;
      autoStart.value = data.auto_start;
    }
  } catch (value) {
    if (sequence !== generation) return;
    if (isApiError(value) && value.status === 404) unsupported.value = true;
    else error.value = failure(value);
  } finally {
    if (sequence === generation) loading.value = false;
  }
}
async function save() {
  if (!settings.value || !changed.value || !password.value || saving.value || freeze.remaining)
    return;
  const id = bots.selectedBot;
  const sequence = generation;
  const enabled = autoStart.value;
  if (
    enabled &&
    !(await confirm({
      title: tr('Enable automatic trading on container startup'),
      message:
        settings.value.role === 'live'
          ? tr(
              'After a container start or restart, the configured live bot may place real orders automatically. Saving this switch does not start trading now. Enable automatic startup?',
            )
          : tr(
              'After a container start or restart, the paper bot will start trading automatically. Saving this switch does not start it now. Enable automatic startup?',
            ),
    }))
  )
    return;
  if (sequence !== generation) return;
  saving.value = true;
  error.value = '';
  notice.value = '';
  try {
    const data = await apiFor(id)<StartupSettings>('/startup-settings', {
      method: 'PUT',
      body: {
        auto_start: enabled,
        revision: settings.value.revision,
        current_password: password.value,
      },
    });
    if (sequence !== generation) return;
    settings.value = data;
    autoStart.value = data.auto_start;
    notice.value = tr(
      'Startup preference saved. It applies on the next container start or restart; the current bot state is unchanged.',
    );
  } catch (value) {
    if (sequence === generation) error.value = failure(value);
  } finally {
    if (sequence === generation) {
      saving.value = false;
      password.value = '';
    }
  }
}
watch(() => bots.selectedBot, load, { immediate: true });
onBeforeUnmount(() => {
  ++generation;
  password.value = '';
});
</script>

<template>
  <section class="workspace-panel max-w-4xl p-6 mb-6" aria-labelledby="startup-settings-heading">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <h2 id="startup-settings-heading" class="section-title">{{ tr('Bot startup') }}</h2>
      <UButton
        color="neutral"
        icon="i-mdi-refresh"
        :loading="loading"
        :disabled="saving"
        @click="load"
      >
        {{ tr('Reload startup settings') }}
      </UButton>
    </div>
    <UAlert v-if="error" role="alert" color="error" :title="error" class="mb-4" />
    <UAlert v-if="notice" role="status" color="info" :title="notice" class="mb-4" />
    <p v-if="loading" class="muted">{{ tr('Loading…') }}</p>
    <p v-else-if="unsupported" class="muted">
      {{
        tr(
          'This bot does not support Web startup settings. Update its NFI image to configure this option.',
        )
      }}
    </p>
    <form v-else-if="settings" class="space-y-5" @submit.prevent="save">
      <UBadge :color="settings.role === 'live' ? 'warning' : 'neutral'">{{
        settings.role === 'live' ? tr('Live trading') : tr('Paper trading')
      }}</UBadge>
      <USwitch
        v-model="autoStart"
        :label="tr('Automatically start the bot when the container starts or restarts')"
        :disabled="saving || (!settings.can_enable && !autoStart)"
      />
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Off by default. This preference is saved on the server for this bot and shared across browsers. It does not start or stop the current trading loop.',
          )
        }}
      </p>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Saving or reloading a trading configuration still leaves the bot stopped. Manual Stop or Pause does not turn off this startup preference.',
          )
        }}
      </p>
      <UAlert
        v-if="!settings.can_enable"
        color="warning"
        :title="
          tr(
            'Configure and successfully load the live trading account before enabling automatic startup.',
          )
        "
      />
      <UFormField :label="tr('Current administrator password')" class="max-w-md">
        <PasswordInput
          v-model="password"
          autocomplete="current-password"
          :disabled="saving"
          :maxlength="1024"
          class="w-full"
        />
      </UFormField>
      <UButton
        type="submit"
        :loading="saving"
        :disabled="!changed || !password || saving || !!freeze.remaining"
        >{{ tr('Save startup preference') }}</UButton
      >
    </form>
  </section>
</template>
