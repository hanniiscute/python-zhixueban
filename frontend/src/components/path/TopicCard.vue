<script setup>
defineProps({
  topic: Object,
  status: String,
})

function getStatusLabel(status) {
  return status === 'completed' ? '✓ 已完成' : status === 'in_progress' ? '学习中' : '🔒'
}
</script>

<template>
  <div class="topic-card" :class="status">
    <div class="topic-status">{{ getStatusLabel(status) }}</div>
    <div class="topic-title">{{ topic?.title || '' }}</div>
  </div>
</template>

<style scoped>
.topic-card {
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
}

.topic-card.completed {
  border-color: #a5d6a7;
  background: #f1f8e9;
}

.topic-card.in_progress {
  border-color: var(--accent-color);
}

.topic-status {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.topic-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}
</style>
