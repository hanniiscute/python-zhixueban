<script setup>
const props = defineProps({
  phases: Array,
  recommendedNext: Object,
})

// 每阶段的完成度：completed/total + 百分比（进度可视化用）
function phaseProgress(phase) {
  const topics = phase.topics || []
  // phase 没有子 topic 时，phase 自身状态就是进度
  if (!topics.length) {
    if (phase.status === 'completed') return { done: 1, total: 1, pct: 100 }
    return { done: 0, total: 1, pct: 0 }
  }
  const done = topics.filter(t => t.status === 'completed').length
  const total = topics.length
  return { done, total, pct: total ? Math.round(done / total * 100) : 0 }
}
</script>

<template>
  <div class="path-timeline">
    <div v-if="recommendedNext?.topic" class="next-step">
      <span class="next-badge">📌 推荐下一步</span>
      <div class="next-card">
        <strong>{{ recommendedNext.topic }}</strong>
        <p>{{ recommendedNext.reason }}</p>
      </div>
    </div>

    <div class="timeline">
      <div
        v-for="phase in phases"
        :key="phase.order"
        class="phase-node"
        :class="{ completed: phase.status === 'completed', active: phase.status === 'in_progress', locked: phase.status === 'locked' }"
      >
        <div class="phase-indicator">
          <span v-if="phase.status === 'completed'" class="phase-check">✓</span>
          <span v-else-if="phase.status === 'in_progress'" class="phase-dot"></span>
          <span v-else class="phase-lock">🔒</span>
        </div>
        <div class="phase-content">
          <div class="phase-title">
            {{ phase.order }}. {{ phase.title }}
            <span
              v-if="phaseProgress(phase).done > 0"
              class="phase-count"
              :class="{ all: phaseProgress(phase).pct === 100 }"
            >{{ phaseProgress(phase).done }}/{{ phaseProgress(phase).total }}</span>
          </div>
          <div class="phase-progress-bar" :title="`完成度 ${phaseProgress(phase).pct}%`">
            <div class="phase-progress-fill" :style="{ width: `${phaseProgress(phase).pct}%` }"></div>
          </div>
          <div class="phase-meta">
            <span>{{ phase.estimated_hours }}小时</span>
            <span v-if="phaseProgress(phase).pct > 0"> · 完成 {{ phaseProgress(phase).pct }}%</span>
          </div>
          <div v-if="phase.topics" class="phase-topics">
            <span
              v-for="topic in phase.topics"
              :key="topic.topic_id || topic.title"
              class="topic-tag"
              :class="topic.status"
            >
              {{ topic.status === 'completed' ? '✓ ' : '' }}{{ topic.title }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.path-timeline {
  padding: 8px;
}

.next-step {
  margin-bottom: 24px;
}

.next-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-color);
}

.next-card {
  border: 2px solid var(--accent-color);
  border-radius: 10px;
  padding: 14px 16px;
  margin-top: 6px;
  background: var(--accent-light);
}

.next-card strong {
  font-size: 15px;
  color: var(--text-primary);
}

.next-card p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 4px 0 0;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
  border-left: 2px solid var(--border-color);
  padding-left: 20px;
}

.phase-node {
  display: flex;
  gap: 12px;
  padding: 12px 0;
  position: relative;
}

.phase-indicator {
  position: absolute;
  left: -29px;
  top: 12px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  background: var(--bg-primary);
  border: 2px solid var(--border-color);
}

.phase-node.completed .phase-indicator {
  background: #4caf50;
  border-color: #4caf50;
  color: white;
}

.phase-node.active .phase-indicator {
  background: var(--accent-color);
  border-color: var(--accent-color);
}

.phase-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: white;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.3); }
}

.phase-content {
  flex: 1;
}

.phase-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 阶段完成计数：3/5 这种 */
.phase-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent-color);
  background: var(--accent-light);
  padding: 1px 8px;
  border-radius: 9px;
}

.phase-count.all {
  color: #059669;
  background: #ecfdf5;
}

/* 阶段进度条 */
.phase-progress-bar {
  height: 6px;
  background: var(--bg-hover);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 8px;
  max-width: 260px;
}

.phase-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-color), #34d399);
  border-radius: 3px;
  transition: width 0.5s ease;
}

.phase-node.completed .phase-progress-fill {
  background: #34d399;
}

.phase-meta {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.phase-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.topic-tag {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
  background: var(--bg-hover);
  color: var(--text-secondary);
}

.topic-tag.completed {
  background: #e8f5e9;
  color: #2e7d32;
}

.topic-tag.in_progress {
  background: var(--accent-light);
  color: var(--accent-color);
  font-weight: 600;
}

.topic-tag.locked {
  opacity: 0.5;
}

.phase-node.locked .phase-title,
.phase-node.locked .phase-meta {
  opacity: 0.5;
}
</style>
