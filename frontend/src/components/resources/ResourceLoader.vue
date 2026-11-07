<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps({
  type: String,
  title: String,
  progress: Number, // 0-1；不传时用内部模拟进度
})

// 各类型的生成步骤与预期耗时（秒）——步骤节奏与真实生成阶段对应
const typeSteps = {
  quiz: {
    expected: 7,
    steps: ['🔍 分析你的学习画像...', '✏️ 设计题目...', '🧩 设置选项与答案...', '📊 调整难度分布...', '🎨 排版题目卡片...'],
  },
  document: {
    expected: 12,
    steps: ['🔍 检索知识库资料...', '📖 组织讲解结构...', '✍️ 撰写讲义内容...', '🎨 排版文档...'],
  },
  mindmap: {
    expected: 10,
    steps: ['🔍 梳理知识结构...', '🌿 展开分支节点...', '🎨 绘制思维导图...'],
  },
  notebook: {
    expected: 15,
    steps: ['🔍 分析代码场景...', '💻 编写示例代码...', '📝 撰写逐行讲解...', '🧪 组织运行结果...'],
  },
  reading: {
    expected: 10,
    steps: ['🔍 检索拓展资料...', '📖 整理阅读材料...', '🎨 排版内容...'],
  },
}

const cfg = computed(() => typeSteps[props.type] || { expected: 10, steps: ['🔍 分析请求...', '✍️ 生成内容...', '🎨 排版...'] })

// 内部模拟进度：随时间渐近 95%，避免卡死在中间
const elapsed = ref(0)
const stepIndex = ref(0)
let timer = null

const currentStep = computed(() => {
  const steps = cfg.value.steps
  return steps[Math.min(stepIndex.value, steps.length - 1)]
})

// 用预期耗时做平滑进度：前 80% 时间走完 70%，之后慢慢逼近 95%
const simProgress = computed(() => {
  const t = elapsed.value / Math.max(cfg.value.expected, 1)
  const p = t < 0.8 ? t * 0.875 : 0.7 + (t - 0.8) * 0.35
  return Math.min(p, 0.95)
})

const barWidth = computed(() => ((props.progress ?? simProgress.value) * 100).toFixed(1))

const typeLabels = {
  document: '正在生成讲解文档',
  mindmap: '正在生成思维导图',
  quiz: '正在出题',
  notebook: '正在准备代码案例',
  reading: '正在整理阅读材料',
}

const typeIcons = {
  document: '📄',
  mindmap: '🧠',
  quiz: '📝',
  notebook: '💻',
  reading: '📖',
}

onMounted(() => {
  timer = setInterval(() => {
    elapsed.value += 0.2
    stepIndex.value = Math.floor(elapsed.value / (cfg.value.expected / cfg.value.steps.length))
  }, 200)
})

onUnmounted(() => clearInterval(timer))
watch(() => props.type, () => { elapsed.value = 0; stepIndex.value = 0 })
</script>

<template>
  <div class="resource-loader">
    <div class="loader-header">
      <span class="loader-icon">{{ typeIcons[type] || '📦' }}</span>
      <div class="loader-info">
        <span class="loader-title">{{ title || typeLabels[type] || '生成中' }}...</span>
        <span class="loader-step">{{ currentStep }}</span>
      </div>
      <span class="loader-time">{{ elapsed.toFixed(0) }}s</span>
    </div>
    <div class="loader-bar-wrapper">
      <div class="loader-bar" :style="{ width: `${barWidth}%` }"></div>
    </div>
  </div>
</template>

<style scoped>
.resource-loader {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px;
  margin: 10px 0;
  background: var(--bg-primary);
}

.loader-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.loader-icon {
  font-size: 28px;
}

.loader-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.loader-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.loader-step {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.loader-time {
  font-size: 12px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.loader-bar-wrapper {
  height: 5px;
  background: var(--bg-hover);
  border-radius: 3px;
  overflow: hidden;
}

.loader-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-color), #60a5fa);
  border-radius: 3px;
  transition: width 0.4s ease;
}
</style>
