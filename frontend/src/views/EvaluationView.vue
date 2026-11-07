<script setup>
import { onMounted, ref } from 'vue'
import { useChatStore } from '../stores/chat'
import { getEvaluation, getStats } from '../api'

const chatStore = useChatStore()
const evaluation = ref(null)
const stats = ref(null)
const loading = ref(true)

onMounted(async () => {
  if (!chatStore.sessionId) {
    loading.value = false
    return
  }

  try {
    const [evalData, statsData] = await Promise.all([
      getEvaluation(chatStore.sessionId),
      getStats(chatStore.sessionId),
    ])
    evaluation.value = evalData
    stats.value = statsData
  } catch (err) {
    console.error(err)
  }
  loading.value = false
})
</script>

<template>
  <div class="evaluation-view">
    <div class="page-header">
      <h2>📊 学习评估</h2>
      <p class="page-desc">多维度追踪学习效果，基于真实学习数据动态评估</p>
    </div>

    <div v-if="loading">加载中...</div>

    <div v-else-if="evaluation" class="evaluation-content">
      <!-- 总体摘要 -->
      <div class="summary-card">
        <h3>📋 总体评估</h3>
        <p>{{ evaluation.summary }}</p>
      </div>

      <!-- 维度雷达图占位 -->
      <div class="dimensions-grid">
        <div v-for="dim in evaluation.dimensions" :key="dim.name" class="dim-eval-card">
          <div class="dim-eval-header">
            <span class="dim-name">{{ dim.name }}</span>
            <span class="dim-trend">{{ dim.trend === 'up' ? '📈' : dim.trend === 'down' ? '📉' : '➡️' }}</span>
          </div>
          <div class="dim-score">{{ dim.score }}</div>
          <div class="dim-detail">{{ dim.detail }}</div>
        </div>
      </div>

      <!-- 调整建议 -->
      <div v-if="evaluation.adjustments?.length" class="adjustments-card">
        <h3>🔧 策略调整建议</h3>
        <div v-for="adj in evaluation.adjustments" :key="adj.reason" class="adj-item">
          <strong>{{ adj.target }}</strong>: {{ adj.action }} — <em>{{ adj.reason }}</em>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <span class="empty-icon">📊</span>
      <p>还没有评估数据</p>
      <p class="empty-hint">完成一些学习内容后，系统会自动生成评估报告</p>
    </div>
  </div>
</template>

<style scoped>
.evaluation-view {
  max-width: 800px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  font-size: 20px;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.page-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.summary-card {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 16px;
  background: var(--bg-primary);
}

.summary-card h3 {
  font-size: 15px;
  margin: 0 0 8px;
  color: var(--text-primary);
}

.summary-card p {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.6;
}

.dimensions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.dim-eval-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 14px;
  text-align: center;
  background: var(--bg-primary);
}

.dim-eval-header {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.dim-name {
  font-size: 13px;
  color: var(--text-muted);
}

.dim-score {
  font-size: 36px;
  font-weight: 700;
  color: var(--accent-color);
}

.dim-detail {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.adjustments-card {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px;
  background: var(--bg-primary);
}

.adjustments-card h3 {
  font-size: 15px;
  margin: 0 0 8px;
}

.adj-item {
  font-size: 13px;
  padding: 6px 0;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-color);
}

.empty-state {
  text-align: center;
  padding: 60px;
  color: var(--text-muted);
}

.empty-icon { font-size: 40px; }
.empty-hint { font-size: 13px; }
</style>
