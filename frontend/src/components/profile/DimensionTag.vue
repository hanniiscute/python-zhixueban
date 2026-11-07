<script setup>
const props = defineProps({
  value: String,
  variant: { type: String, default: 'default' }, // default, level, interest, error, pace
})
</script>

<template>
  <span class="dim-tag" :class="[`tag-${variant}`, { empty: !value || value === '待探索' || value === '待积累' }]">
    {{ value || '待探索' }}
  </span>
</template>

<style scoped>
.dim-tag {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
  color: var(--text-secondary);
  background: var(--bg-hover);
  font-weight: 500;
  white-space: nowrap;
}

.tag-level {
  background: #e8f5e9;
  color: #2e7d32;
  font-weight: 600;
}

.tag-interest {
  background: #e3f2fd;
  color: #1565c0;
}

.tag-error {
  background: #fff3e0;
  color: #e65100;
}

.tag-pace {
  background: #f3e5f5;
  color: #7b1fa2;
}

.empty {
  opacity: 0.5;
  font-style: italic;
}
</style>
