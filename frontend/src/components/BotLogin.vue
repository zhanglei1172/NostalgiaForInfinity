<script setup lang="ts">
import { tr } from '@/i18n';
import { useAuthFreeze } from '@/composables/authFreeze';
import type { AuthPayload, AuthStorageWithBotId } from '@/types';

import { useRoute, useRouter } from 'vue-router';

const props = withDefaults(
  defineProps<{
    inModal?: boolean;
    existingAuth?: AuthStorageWithBotId;
  }>(),
  {
    inModal: false,
    existingAuth: undefined,
  },
);
const emit = defineEmits<{ loginResult: [value: boolean] }>();

const defaultURL = window.location.origin || 'http://localhost:3000';

const router = useRouter();
const route = useRoute();
const botStore = useBotStore();

const nameState = ref<boolean>();
const pwdState = ref<boolean>();
const urlState = ref<boolean>();
const errorMessage = ref<string>('');
const submitting = ref(false);
const errorMessageCORS = ref<boolean>(false);
const formRef = ref<HTMLFormElement>();
const botEdit = ref<boolean>(false);
const auth = ref<AuthPayload>({
  botName: '',
  url: defaultURL,
  username: '',
  password: '',
});

const freeze = useAuthFreeze(() => auth.value.url);

function emitLoginResult(value: boolean) {
  emit('loginResult', value);
}

const urlDuplicate = computed<boolean>(() => {
  const bots = Object.values(botStore.availableBots).find((bot) => bot.botUrl === auth.value.url);
  return !botEdit.value && bots !== undefined;
});

function checkFormValidity() {
  const valid = formRef.value?.checkValidity();
  nameState.value = valid || auth.value.username !== '';
  pwdState.value = valid || auth.value.password !== '';
  urlState.value = valid || auth.value.url !== '';
  return valid;
}

function resetLogin() {
  auth.value.botName = '';
  auth.value.url = defaultURL;
  auth.value.username = '';
  auth.value.password = '';
  nameState.value = undefined;
  pwdState.value = undefined;
  urlState.value = undefined;
  errorMessage.value = '';
  botEdit.value = false;
}

function handleReset(evt) {
  evt.preventDefault();
  resetLogin();
}

async function handleSubmit() {
  // Exit when the form isn't valid
  if (submitting.value || freeze.remaining || !checkFormValidity()) {
    return;
  }
  errorMessage.value = '';
  submitting.value = true;
  // Push the name to submitted names
  try {
    const botId =
      botEdit.value && props.existingAuth ? props.existingAuth.botId : botStore.nextBotId;
    const { login } = useLoginInfo(botId);
    await login(auth.value);
    if (botEdit.value) {
      // Bot editing ...
      const thisBot = botStore.botStores[botId];
      if (thisBot) {
        thisBot.isBotLoggedIn = true;
        thisBot.isBotOnline = true;
      }
      // botStore.allRefreshFull();
      emitLoginResult(true);
    } else {
      // Add new bot
      const sortId = Object.keys(botStore.availableBots).length + 1;
      botStore.addBot({
        botName: auth.value.botName,
        botId,
        botUrl: auth.value.url,
        sortId: sortId,
      });
      // switch to newly added bot
      botStore.selectBot(botId);
      emitLoginResult(true);
      botStore.allRefreshFull();
    }

    if (props.inModal === false) {
      if (typeof route?.query.redirect === 'string') {
        const resolved = router.resolve({ path: route.query.redirect });
        if (resolved.name === '/[...path]') {
          router.push('/');
        } else {
          router.push(resolved.path);
        }
      } else {
        router.push('/dashboard');
      }
    }
  } catch (error) {
    errorMessageCORS.value = false;
    // this.nameState = false;

    if (freeze.capture(error)) {
      auth.value.password = '';
    } else if (isApiError(error) && error.data?.detail === 'account_guard_unavailable') {
      errorMessage.value = tr(
        'Password protection storage is unavailable. Verification is blocked; check storage permissions.',
      );
    } else if (isApiError(error) && error.status === 401) {
      nameState.value = false;
      pwdState.value = false;
      errorMessage.value = tr(
        'Connected to bot, however Login failed, Username or Password wrong.',
      );
    } else {
      urlState.value = false;
      errorMessage.value = tr(
        'Please verify that the bot is running, the Bot API is enabled and the URL is reachable. You can verify this by navigating to {0}/api/v1/ping to make sure the bot API is reachable',
        { 0: auth.value.url },
      );
      if (auth.value.url !== window.location.origin) {
        errorMessageCORS.value = true;
      }
    }
    console.error(errorMessage.value);
    emitLoginResult(false);
  } finally {
    submitting.value = false;
  }
}

function handleOk(evt) {
  evt.preventDefault();
  handleSubmit();
}

function reset() {
  resetLogin();
  if (props.existingAuth) {
    botEdit.value = true;
    auth.value.botName = props.existingAuth.botName;
    auth.value.url = props.existingAuth.apiUrl;
    auth.value.username = props.existingAuth.username ?? '';
  }
}

defineExpose({
  reset,
});

onMounted(() => {
  reset();
});
</script>

<template>
  <form ref="formRef" novalidate @submit.stop.prevent="handleSubmit" @reset="handleReset">
    <UAlert
      v-if="freeze.remaining"
      role="alert"
      color="warning"
      :title="freeze.message"
      class="mb-4"
    />
    <UFormField class="mb-4" :label="tr('Bot Name')">
      <UInput
        v-model="auth.botName"
        :placeholder="tr('Bot Name')"
        class="mt-1 block w-full"
        @keydown.enter="handleOk"
      />
    </UFormField>
    <UFormField
      class="mb-4"
      :label="tr('API Url')"
      :error="urlState === false ? tr('API URL is required.') : undefined"
    >
      <UInput
        id="url-input"
        v-model="auth.url"
        required
        trim
        class="mt-1 block w-full"
        @keydown.enter="handleOk"
      />
      <UAlert
        v-if="urlDuplicate"
        class="mt-2"
        color="warning"
        :title="tr('This URL is already in use by another bot.')"
      >
      </UAlert>
    </UFormField>
    <UFormField
      class="mb-4"
      :label="tr('Username')"
      :error="nameState === false ? tr('Name and Password are required.') : undefined"
    >
      <UInput
        v-model="auth.username"
        autocomplete="username"
        required
        placeholder="Freqtrader"
        class="w-full"
        @keydown.enter="handleOk"
      />
    </UFormField>
    <UFormField
      class="mb-4"
      :label="tr('Password')"
      :error="pwdState === false ? tr('Invalid Password') : undefined"
    >
      <PasswordInput
        v-model="auth.password"
        autocomplete="current-password"
        required
        class="w-full"
        @keydown.enter="handleOk"
      />
    </UFormField>
    <div>
      <UAlert
        v-if="errorMessage"
        class="mt-2 whitespace-pre-line"
        color="warning"
        :title="tr('Login failed')"
      >
        <template #description>
          {{ errorMessage }}
          <span v-if="errorMessageCORS">
            {{ tr("Please also check your bot's CORS configuration:") }}
            <a
              href="https://www.freqtrade.io/en/latest/rest-api/#cors"
              class="text-blue-500 underline"
              >{{ tr('Freqtrade CORS documentation') }}</a
            >
          </span>
        </template>
      </UAlert>
    </div>
    <div class="flex justify-end gap-2 mt-4">
      <UButton :label="tr('Reset')" color="error" type="reset" />
      <UButton
        v-if="inModal"
        :label="tr('Cancel')"
        color="neutral"
        type="button"
        @click="emitLoginResult(true)"
      />
      <UButton
        :label="tr('Submit')"
        :loading="submitting"
        :disabled="!!freeze.remaining"
        variant="solid"
        color="primary"
        type="submit"
        icon="mdi:login"
      />
    </div>
  </form>
</template>
