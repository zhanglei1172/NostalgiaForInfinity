<script setup lang="ts">
import { tr } from '@/i18n';
import type { AuthStorageWithBotId } from '@/types';

export interface LoginModalProps {
  loginInfo?: AuthStorageWithBotId;
}

defineProps<LoginModalProps>();
const emit = defineEmits<{
  close: [value: boolean];
}>();

function loginResult(result: boolean) {
  if (result) {
    // Only close if
    emit('close', result);
  }
}
</script>

<template>
  <UModal
    :title="tr('Login to your bot')"
    :description="tr('Enter your bot credentials to connect')"
  >
    <template #body>
      <BotLogin in-modal :existing-auth="loginInfo" @login-result="loginResult" />
    </template>
  </UModal>
</template>
