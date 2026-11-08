<script setup lang="ts">
import { language, setLanguage, tr } from '@/i18n';

const choices = [
  { label: '简体中文', value: 'zh-CN' },
  { label: 'English', value: 'en' },
];
</script>

<template>
  <USelect
    :model-value="language"
    :items="choices"
    :aria-label="tr('Interface language')"
    icon="i-mdi-translate"
    class="w-36 shrink-0"
    @update:model-value="setLanguage"
  />
</template>
