<script setup lang="ts">
import { tr } from '@/i18n';
</script>

<template>
  <div>
    <h1 class="mb-5">{{ tr('404 Error.') }}</h1>
    <p class="h4">{{ tr('Ahhhhhhhh! The page you are looking for does not exist.') }}</p>
    <p>
      {{ tr("Don't worry, you can head back to") }}
      <RouterLink to="/">
        <span>{{ tr('the main page') }}</span> </RouterLink
      >.
    </p>
  </div>
</template>
