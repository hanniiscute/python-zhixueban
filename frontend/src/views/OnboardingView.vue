<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat'
import { saveQuestionnaire } from '../api'

const router = useRouter()
const chatStore = useChatStore()

const currentStep = ref(0)
const submitting = ref(false)
const done = ref(false)
const savedDimensions = ref([])

const questions = [
  {
    key: 'programming_level',
    title: '你的编程基础如何？',
    desc: '帮助我们匹配适合你的学习起点',
    icon: '💻',
    options: [
      { value: 'zero', label: '完全零基础', emoji: '🌱' },
      { value: 'little', label: '了解过一点', emoji: '🌿' },
      { value: 'some', label: '有一定基础', emoji: '🪴' },
      { value: 'proficient', label: '比较熟练', emoji: '🌳' },
    ],
  },
  {
    key: 'learning_style',
    title: '你更喜欢哪种学习方式？',
    desc: '我们会优先用你喜欢的方式呈现内容',
    icon: '📖',
    options: [
      { value: 'video', label: '看视频跟着学', emoji: '🎬' },
      { value: 'reading', label: '阅读文档自学', emoji: '📄' },
      { value: 'project', label: '动手做项目', emoji: '🔧' },
      { value: 'practice', label: '刷题练习', emoji: '✏️' },
    ],
  },
  {
    key: 'learning_goal',
    title: '你学习 Python 的主要目标？',
    desc: '我们会围绕你的目标规划学习路径',
    icon: '🎯',
    options: [
      { value: 'exam', label: '通过考试', emoji: '📝' },
      { value: 'job', label: '找工作 / 面试', emoji: '💼' },
      { value: 'personal', label: '做个人项目', emoji: '🚀' },
      { value: 'upskill', label: '提升技能', emoji: '📈' },
      { value: 'research', label: '学术研究', emoji: '🔬' },
    ],
  },
  {
    key: 'interest_area',
    title: '你对哪个方向最感兴趣？',
    desc: '我们会在学习内容中融入你感兴趣的方向',
    icon: '🧭',
    options: [
      { value: 'data_ai', label: '数据分析 / AI', emoji: '🤖' },
      { value: 'web', label: 'Web 开发', emoji: '🌐' },
      { value: 'game', label: '游戏开发', emoji: '🎮' },
      { value: 'automation', label: '自动化脚本', emoji: '⚡' },
      { value: 'algorithm', label: '算法', emoji: '🧩' },
    ],
  },
  {
    key: 'daily_hours',
    title: '每天能投入多少时间学习？',
    desc: '我们会根据你的时间安排调整任务量',
    icon: '⏰',
    options: [
      { value: '<30min', label: '少于 30 分钟', emoji: '☕' },
      { value: '30min-1h', label: '30 分钟 ~ 1 小时', emoji: '⏱️' },
      { value: '1-2h', label: '1 ~ 2 小时', emoji: '📚' },
      { value: '>2h', label: '2 小时以上', emoji: '🔥' },
    ],
  },
  {
    key: 'thinking_style',
    title: '学习新概念时，你通常会？',
    desc: '帮助我们理解你的思维方式',
    icon: '🧠',
    options: [
      { value: 'memorize', label: '先记住再说', emoji: '📋' },
      { value: 'understand', label: '理解原理再动手', emoji: '🔍' },
      { value: 'try', label: '直接上手试一试', emoji: '🏃' },
      { value: 'compare', label: '对比不同方案', emoji: '⚖️' },
    ],
  },
]

const totalSteps = questions.length
const answers = ref({})

function selectOption(qkey, value) {
  answers.value[qkey] = value
  if (currentStep.value < totalSteps - 1) {
    setTimeout(() => currentStep.value++, 250)
  } else {
    submitAll()
  }
}

function prevStep() {
  if (currentStep.value > 0) currentStep.value--
}

async function submitAll() {
  if (submitting.value || done.value) return
  submitting.value = true
  try {
    const res = await saveQuestionnaire({
      user_id: chatStore.userId,
      session_id: chatStore.sessionId,
      answers: answers.value,
    })
    savedDimensions.value = res.dimensions_filled || []
    done.value = true
  } catch (err) {
    console.error('问卷提交失败:', err)
  }
  submitting.value = false
}

function goHome() {
  localStorage.setItem('onboarding_done', '1')
  router.push('/')
}

function skip() {
  localStorage.setItem('onboarding_done', '1')
  router.push('/')
}
</script>

<template>
  <div class="onboarding-page">
    <!-- 完成页 -->
    <div v-if="done" class="done-card">
      <div class="done-icon">🎉</div>
      <h2>画像构建完成！</h2>
      <p>已从你的回答中提取了 {{ savedDimensions.length }} 个维度的初始画像</p>
      <div class="dim-tags">
        <span v-for="d in savedDimensions" :key="d" class="dim-tag">{{ d }}</span>
      </div>
      <button class="enter-btn" @click="goHome">进入学习 →</button>
    </div>

    <!-- 问卷主体 -->
    <div v-else class="question-card">
      <!-- 进度条 -->
      <div class="progress-top">
        <div class="progress-dots">
          <span
            v-for="(q, i) in questions"
            :key="q.key"
            class="dot"
            :class="{ filled: i < currentStep || answers[q.key], current: i === currentStep }"
          ></span>
        </div>
        <span class="step-count">{{ currentStep + 1 }} / {{ totalSteps }}</span>
        <button class="skip-btn" @click="skip">跳过 →</button>
      </div>

      <!-- 当前问题 -->
      <div class="question-body">
        <div class="q-icon">{{ questions[currentStep].icon }}</div>
        <h3 class="q-title">{{ questions[currentStep].title }}</h3>
        <p class="q-desc">{{ questions[currentStep].desc }}</p>

        <div class="options-list">
          <button
            v-for="opt in questions[currentStep].options"
            :key="opt.value"
            class="option-btn"
            :class="{ selected: answers[questions[currentStep].key] === opt.value }"
            :disabled="submitting"
            @click="selectOption(questions[currentStep].key, opt.value)"
          >
            <span class="opt-emoji">{{ opt.emoji }}</span>
            <span class="opt-label">{{ opt.label }}</span>
          </button>
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="question-footer">
        <button v-if="currentStep > 0" class="back-btn" @click="prevStep">← 上一题</button>
        <span v-else></span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.onboarding-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
  padding: 20px;
}

/* ── 完成页 ── */
.done-card {
  text-align: center;
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  padding: 48px 40px;
  max-width: 420px;
  width: 100%;
  color: #fff;
}

.done-icon {
  font-size: 56px;
  margin-bottom: 12px;
}

.done-card h2 {
  font-size: 22px;
  margin: 0 0 8px;
}

.done-card p {
  font-size: 14px;
  opacity: 0.7;
  margin: 0 0 20px;
}

.dim-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-bottom: 28px;
}

.dim-tag {
  font-size: 12px;
  padding: 4px 12px;
  background: rgba(255,255,255,0.1);
  border-radius: 12px;
}

.enter-btn {
  padding: 12px 40px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.enter-btn:hover {
  opacity: 0.9;
}

/* ── 问题卡片 ── */
.question-card {
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  padding: 32px 36px 24px;
  max-width: 480px;
  width: 100%;
  color: #fff;
}

.progress-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 32px;
}

.progress-dots {
  display: flex;
  gap: 6px;
  flex: 1;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255,255,255,0.2);
  transition: all 0.25s;
}

.dot.filled {
  background: #667eea;
}

.dot.current {
  background: #fff;
  box-shadow: 0 0 8px rgba(255,255,255,0.5);
  transform: scale(1.3);
}

.step-count {
  font-size: 12px;
  opacity: 0.5;
}

.skip-btn {
  background: none;
  border: none;
  color: rgba(255,255,255,0.4);
  font-size: 13px;
  cursor: pointer;
}

.skip-btn:hover {
  color: rgba(255,255,255,0.7);
}

.question-body {
  text-align: center;
  margin-bottom: 24px;
}

.q-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.q-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 6px;
}

.q-desc {
  font-size: 13px;
  opacity: 0.5;
  margin: 0 0 24px;
}

.options-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.option-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: rgba(255,255,255,0.05);
  border: 1.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  color: #fff;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  width: 100%;
}

.option-btn:hover {
  background: rgba(255,255,255,0.1);
  border-color: rgba(255,255,255,0.25);
}

.option-btn.selected {
  background: rgba(102, 126, 234, 0.2);
  border-color: #667eea;
}

.option-btn:disabled {
  pointer-events: none;
  opacity: 0.6;
}

.opt-emoji {
  font-size: 22px;
  flex-shrink: 0;
}

.opt-label {
  font-size: 14px;
}

.question-footer {
  display: flex;
  justify-content: space-between;
}

.back-btn {
  background: none;
  border: none;
  color: rgba(255,255,255,0.4);
  font-size: 13px;
  cursor: pointer;
}

.back-btn:hover {
  color: rgba(255,255,255,0.7);
}
</style>
