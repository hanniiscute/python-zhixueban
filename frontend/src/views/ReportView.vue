<script setup>
import { onMounted, ref, computed } from 'vue'
import { marked } from 'marked'
import { useChatStore } from '../stores/chat'
import { generateReport, getCachedReport } from '../api'

const chatStore = useChatStore()

const loading = ref(true)
const generating = ref(false)
const error = ref('')
const reportMd = ref('')
const generatedAt = ref('')
const stats = ref(null)

const reportHtml = computed(() => {
  if (!reportMd.value) return ''
  try {
    return marked.parse(reportMd.value)
  } catch {
    return reportMd.value
  }
})

const statCards = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { icon: '⏱️', label: '累计学习', value: `${s.total_learning_minutes}`, unit: '分钟' },
    { icon: '✅', label: '完成主题', value: `${s.topics_completed}`, unit: '个' },
    { icon: '🏋️', label: '练习次数', value: `${s.quiz_attempts}`, unit: '次' },
    { icon: '🎯', label: '平均正确率', value: `${s.quiz_accuracy}`, unit: '%' },
    { icon: '🔥', label: '连续学习', value: `${s.daily_streak}`, unit: '天' },
    { icon: '💬', label: '提问次数', value: `${s.questions_asked}`, unit: '次' },
  ]
})

async function loadCached() {
  loading.value = true
  try {
    const data = await getCachedReport(chatStore.sessionId)
    if (data?.report) {
      reportMd.value = data.report
      generatedAt.value = data.generated_at || ''
      stats.value = data.stats || null
    }
  } catch (err) {
    console.error('读取缓存报告失败:', err)
  }
  loading.value = false
}

async function generate() {
  generating.value = true
  error.value = ''
  try {
    const data = await generateReport(chatStore.sessionId)
    reportMd.value = data.report
    generatedAt.value = data.generated_at || ''
    stats.value = data.stats || null
  } catch (err) {
    error.value = err.message || '报告生成失败，请重试'
  } finally {
    generating.value = false
  }
}

onMounted(loadCached)
</script>

<template>
  <div class="report-view">
    <div class="page-header">
      <h2>📈 学习报告</h2>
      <p class="page-desc">AI 根据你的学习数据生成的个性化分析</p>
    </div>

    <div v-if="loading" class="empty-state">
      <div class="empty-icon">📈</div>
      <p>正在加载...</p>
    </div>

    <template v-else>
      <!-- 数据概览卡片 -->
      <div v-if="statCards.length" class="stats-grid">
        <div v-for="c in statCards" :key="c.label" class="stat-card">
          <span class="stat-icon">{{ c.icon }}</span>
          <span class="stat-value">{{ c.value }}<small>{{ c.unit }}</small></span>
          <span class="stat-label">{{ c.label }}</span>
        </div>
      </div>

      <!-- 生成按钮 / 报告 -->
      <div v-if="!reportMd" class="empty-state">
        <div class="empty-icon">🤖</div>
        <h3>还没有学习报告</h3>
        <p class="empty-desc">AI 会汇总你的学习时长、练习成绩、错题分布和画像，<br />生成一份专属分析报告。</p>
        <button class="generate-btn" :disabled="generating" @click="generate">
          {{ generating ? '⏳ AI 正在分析你的学习数据…' : '✨ 生成我的学习报告' }}
        </button>
        <p v-if="error" class="error-line">{{ error }}</p>
      </div>

      <div v-else class="report-body">
        <div class="report-meta">
          <span v-if="generatedAt">生成于 {{ generatedAt }}</span>
          <button class="regen-btn" :disabled="generating" @click="generate">
            {{ generating ? '⏳ 重新分析中…' : '🔄 重新生成' }}
          </button>
        </div>
        <div v-if="generating" class="generating-tip">
          <span class="spin"></span> AI 正在结合你的最新数据重新生成报告，约需 10~30 秒…
        </div>
        <div class="report-markdown" v-html="reportHtml"></div>
        <p v-if="error" class="error-line">{{ error }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.report-view {
  max-width: 700px;
  margin: 0 auto;
  padding-bottom: 40px;
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-primary);
}

.stat-icon { font-size: 18px; }

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value small {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 3px;
}

.stat-label {
  font-size: 12px;
  color: var(--text-muted);
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
}

.empty-icon {
  font-size: 42px;
  margin-bottom: 10px;
}

.empty-state h3 {
  color: var(--text-primary);
  margin: 0 0 8px;
}

.empty-desc {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.8;
  margin: 0 0 18px;
}

.generate-btn {
  padding: 10px 28px;
  border: none;
  border-radius: 8px;
  background: var(--accent-color);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.generate-btn:hover { background: var(--accent-hover); }
.generate-btn:disabled { opacity: 0.6; cursor: wait; }

.error-line {
  margin-top: 12px;
  font-size: 13px;
  color: #dc2626;
}

.report-body {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-primary);
  overflow: hidden;
}

.report-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--text-muted);
}

.regen-btn {
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.regen-btn:hover {
  border-color: var(--accent-color);
  color: var(--accent-color);
}

.generating-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px;
  font-size: 13px;
  color: var(--text-muted);
  background: var(--bg-secondary, #f8f9fb);
}

.spin {
  width: 12px;
  height: 12px;
  border: 2px solid var(--accent-light);
  border-top-color: var(--accent-color);
  border-radius: 50%;
  animation: r-spin 0.8s linear infinite;
}

@keyframes r-spin { to { transform: rotate(360deg); } }

.report-markdown {
  padding: 20px 22px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-primary);
}

.report-markdown :deep(h2) { font-size: 16px; margin: 18px 0 8px; }
.report-markdown :deep(h2:first-child) { margin-top: 0; }
.report-markdown :deep(h3) { font-size: 14px; margin: 14px 0 6px; }
.report-markdown :deep(p) { margin: 8px 0; }
.report-markdown :deep(ul), .report-markdown :deep(ol) { padding-left: 20px; margin: 8px 0; }
.report-markdown :deep(li) { margin: 4px 0; }
.report-markdown :deep(strong) { color: var(--accent-color); }
.report-markdown :deep(blockquote) {
  margin: 8px 0;
  padding: 6px 12px;
  border-left: 3px solid var(--accent-color);
  background: var(--bg-hover);
  color: var(--text-secondary);
}
</style>
