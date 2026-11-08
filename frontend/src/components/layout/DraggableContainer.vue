<script setup lang="ts">
defineOptions({
  inheritAttrs: false,
});
withDefaults(
  defineProps<{
    /** The header text for the draggable container */
    header?: string;
    /** The info text for the draggable container
     * Only shown when hovering the info icon next to the header. Used to give more context about the content of the container.
     * Not compatible with usage of the header slot.
     */
    infoText?: string;
  }>(),
  {
    header: '',
    infoText: '',
  },
);
</script>

<template>
  <div class="workspace-panel flex flex-col h-full w-full">
    <div class="panel-heading drag-header">
      <slot name="header">
        <div class="flex items-center gap-2">
          {{ header }}
          <InfoBox v-if="infoText" :hint="infoText" />
        </div>
      </slot>
    </div>
    <div class="panel-content p-0 min-h-0 grow w-full overflow-auto" v-bind="$attrs">
      <slot></slot>
    </div>
  </div>
</template>
