<script setup lang="ts">
import { tr } from '@/i18n';
</script>
<template>
  <div class="workspace-page logs-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ tr('OBSERVABILITY') }}</p>
        <h1>{{ tr('Logs') }}</h1>
        <p>
          {{
            tr(
              'Find strategy activity and connection issues. Filter by level or search the original messages.',
            )
          }}
        </p>
      </div>
    </div>
    <LogViewer class="logs-frame" />
  </div>
</template>
<style scoped>
.logs-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.logs-frame {
  flex: 1;
  min-height: 400px;
}
</style>
