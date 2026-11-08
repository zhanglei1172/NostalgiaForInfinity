<script setup lang="ts">
import { tr } from '@/i18n';
definePage({ meta: { allowAnonymous: true } });
const botStore = useBotStore();
</script>
<template>
  <div class="workspace-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">NOSTALGIA FOR INFINITY</p>
        <h1>{{ tr('Connections') }}</h1>
        <p>{{ tr('Connect your bots and choose an account to monitor.') }}</p>
      </div>
      <UButton v-if="botStore.hasBots" to="/dashboard" icon="i-mdi-arrow-right" trailing>{{
        tr('Account overview')
      }}</UButton>
    </div>
    <div class="workspace-panel p-6 max-w-3xl"><BotList /></div>
    <UButton v-if="!botStore.hasBots" to="/login" icon="i-mdi-login" class="mt-6">{{
      tr('Login')
    }}</UButton>
  </div>
</template>
