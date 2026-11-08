<script setup lang="ts">
import { tr } from '@/i18n';
defineOptions({ inheritAttrs: false });
const value = defineModel<string>({ default: '' });
const visible = ref(false);
</script>
<template>
  <UInput
    v-bind="$attrs"
    v-model="value"
    :type="visible ? 'text' : 'password'"
    class="w-full"
    :ui="{ trailing: 'pe-1' }"
  >
    <template #trailing
      ><UButton
        type="button"
        color="neutral"
        variant="ghost"
        size="sm"
        :icon="visible ? 'i-mdi-eye-off-outline' : 'i-mdi-eye-outline'"
        :aria-label="visible ? tr('Hide password') : tr('Show password')"
        :aria-pressed="visible"
        @click="visible = !visible"
    /></template>
  </UInput>
</template>
