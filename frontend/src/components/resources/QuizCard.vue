<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import { explainMistakes } from '../../api'
import { useChatStore } from '../../stores/chat'

const chatStore = useChatStore()

const props = defineProps({
  data: Object,
  passLine: { type: Number, default: 60 },
  onSubmitted: { type: Function, default: null },
})

const emit = defineEmits(['quiz-submitted'])

const userAnswers = ref({})
const submitted = ref(false)
const score = ref(null)

// ===== 错题针对性讲解 =====
const aiExplanation = ref('')      // AI 生成的错题讲解（Markdown → HTML）
const explainLoading = ref(false)
const explainError = ref('')
const aiExplained = ref(false)     // 本次提交是否已请求过讲解（重新作答后重置）

const aiExplanationHtml = computed(() => {
  if (!aiExplanation.value) return ''
  try {
    return marked.parse(aiExplanation.value)
  } catch {
    return aiExplanation.value
  }
})

// 组装错题明细（提交上报错题本、AI 讲解共用同一份数据）
function buildMistakes() {
  return (props.data?.questions || [])
    .filter(q => {
      const gradable = isMulti(q) || (q.answer !== undefined && q.answer !== null && q.answer !== '')
      if (!gradable) return false
      if (isMulti(q)) {
        const picked = (Array.isArray(userAnswers.value[q.id]) ? userAnswers.value[q.id] : []).slice().sort()
        const right = q.answers.slice().sort()
        return !(picked.length === right.length && picked.every((v, i) => v === right[i]))
      }
      return userAnswers.value[q.id] !== q.answer
    })
    .map(q => ({
      stem: q.stem,
      options: (q.options || []).map(o => `${o.key}. ${o.text}`),
      answer: isMulti(q) ? q.answers.join('') : q.answer,
      user_answer: isMulti(q) ? (userAnswers.value[q.id] || []).join('') : (userAnswers.value[q.id] || '未作答'),
      explanation: q.explanation || '',
    }))
}

async function requestExplanation() {
  const mistakes = buildMistakes()
  if (!mistakes.length) return

  explainLoading.value = true
  explainError.value = ''
  try {
    const res = await explainMistakes(chatStore.sessionId, props.data?.title || '', mistakes)
    aiExplanation.value = res.explanation || ''
  } catch (e) {
    explainError.value = e.message || '讲解生成失败'
  } finally {
    explainLoading.value = false
    aiExplained.value = true
  }
}

const isPassed = computed(() => {
  if (!score.value || score.value.total === 0) return false
  return (score.value.correct / score.value.total * 100) >= props.passLine
})

// 多选题：答案存 answers 数组（如 ["A","B","C"]），单选题存 answer 字符串
function isMulti(q) {
  return Array.isArray(q.answers) && q.answers.length > 0
}

function isSelected(q, key) {
  const val = userAnswers.value[q.id]
  if (isMulti(q)) return Array.isArray(val) && val.includes(key)
  return val === key
}

function selectAnswer(questionId, key, q) {
  if (submitted.value) return
  if (isMulti(q)) {
    const cur = new Set(Array.isArray(userAnswers.value[questionId]) ? userAnswers.value[questionId] : [])
    if (cur.has(key)) cur.delete(key)
    else cur.add(key)
    userAnswers.value[questionId] = [...cur].sort()
  } else {
    userAnswers.value[questionId] = key
  }
}

function checkAnswers() {
  if (!props.data?.questions) return
  let correct = 0
  let total = 0
  props.data.questions.forEach(q => {
    // 只有带标准答案的客观题可自动判分；编程题/开放题不计入总分，
    // 否则 5 题里夹 2 道不可判分题，全对也只有 60%，永远卡在及格线上。
    const gradable = isMulti(q) || (q.answer !== undefined && q.answer !== null && q.answer !== '')
    if (!gradable) return
    total++
    if (isMulti(q)) {
      const picked = (Array.isArray(userAnswers.value[q.id]) ? userAnswers.value[q.id] : []).slice().sort()
      const right = q.answers.slice().sort()
      if (picked.length === right.length && picked.every((v, i) => v === right[i])) correct++
    } else if (userAnswers.value[q.id] === q.answer) {
      correct++
    }
  })
  score.value = { correct, total }
  submitted.value = true
  // 错题明细一并抛给父组件 → 上报后端错题本
  const payload = { correct, total, mistakes: buildMistakes() }
  // 通知父组件：兼容 prop 回调与 Vue 事件两种写法
  if (props.onSubmitted) {
    props.onSubmitted(payload)
  }
  emit('quiz-submitted', payload)
}

function resetQuiz() {
  userAnswers.value = {}
  submitted.value = false
  score.value = null
  aiExplanation.value = ''
  explainError.value = ''
  aiExplained.value = false
}

defineExpose({ resetQuiz })
</script>

<template>
  <div v-if="data" class="quiz-card">
    <div class="quiz-header">
      <span class="quiz-label">📝 {{ data.title || '练习题' }}</span>
      <span v-if="data.levels" class="quiz-levels">
        <span class="level-tag basic">{{ data.levels.basic?.count }}道基础</span>
        <span class="level-tag mid">{{ data.levels.intermediate?.count }}道进阶</span>
        <span class="level-tag adv">{{ data.levels.advanced?.count }}道挑战</span>
      </span>
    </div>

    <div v-for="(q, idx) in data.questions" :key="q.id" class="question-item">
      <div class="question-stem">
        <span class="q-number">{{ idx + 1 }}.</span>
        <span class="q-type-badge" :class="q.level">{{ q.level === 'basic' ? '基础' : q.level === 'intermediate' ? '进阶' : '挑战' }}</span>
        {{ q.stem }}
      </div>

      <!-- 选择题选项 -->
      <div v-if="q.options" class="options-list">
        <div
          v-for="opt in q.options"
          :key="opt.key"
          class="option-item"
          :class="{
            selected: isSelected(q, opt.key),
            correct: submitted && opt.key === q.answer || (submitted && isMulti(q) && q.answers.includes(opt.key)),
            wrong: submitted && isSelected(q, opt.key) && !(isMulti(q) ? q.answers.includes(opt.key) : opt.key === q.answer),
          }"
          @click="selectAnswer(q.id, opt.key, q)"
        >
          <span class="option-key">{{ opt.key }}</span>
          <span class="option-text">{{ opt.text }}</span>
        </div>
      </div>

      <!-- 编程题占位 -->
      <div v-if="q.type === 'code'" class="code-question">
        <pre class="starter-code">{{ q.starter_code }}</pre>
        <textarea class="code-input" placeholder="在此编写你的答案..."></textarea>
      </div>

      <!-- 开放题占位 -->
      <div v-if="q.type === 'open'" class="open-question">
        <textarea class="open-input" placeholder="请输入你的思考..."></textarea>
      </div>

      <!-- 解析 -->
      <div v-if="submitted && q.explanation" class="explanation">
        💡 {{ q.explanation }}
      </div>
    </div>

    <div class="quiz-actions">
      <button v-if="!submitted" class="submit-btn" @click="checkAnswers">提交答案</button>
      <div v-else class="score-display">
        <span class="score-text">
          得分: {{ score?.correct }} / {{ score?.total }}
          <span v-if="isPassed" class="pass-badge">✅ 通过</span>
          <span v-else class="fail-badge">❌ 未通过</span>
        </span>
        <button class="retry-btn" @click="resetQuiz">重新作答</button>
      </div>
    </div>

    <!-- AI 错题讲解：有错题且未通过时展示入口 -->
    <div v-if="submitted && score && score.correct < score.total" class="ai-explain-section">
      <button
        v-if="!aiExplained && !explainLoading"
        class="explain-btn"
        @click="requestExplanation"
      >
        🤖 让 AI 讲解我的错题
      </button>
      <div v-else-if="explainLoading" class="explain-loading">
        <span class="explain-spinner"></span> AI 正在分析你的错题…
      </div>
      <div v-else-if="explainError" class="explain-error">
        {{ explainError }}
        <button class="explain-retry" @click="requestExplanation">重试</button>
      </div>
      <div v-else-if="aiExplanation" class="ai-explanation" v-html="aiExplanationHtml"></div>
    </div>
  </div>
</template>

<style scoped>
.quiz-card {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 16px;
  margin: 10px 0;
  background: var(--bg-primary);
}

.quiz-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}

.quiz-label {
  font-weight: 600;
  font-size: 15px;
}

.quiz-levels {
  display: flex;
  gap: 4px;
}

.level-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
}

.level-tag.basic { background: #e8f5e9; color: #2e7d32; }
.level-tag.mid { background: #fff3e0; color: #e65100; }
.level-tag.adv { background: #fce4ec; color: #c62828; }

.question-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color);
}

.question-item:last-child {
  border-bottom: none;
}

/* ===== AI 错题讲解 ===== */
.ai-explain-section {
  margin-top: 12px;
}

.explain-btn {
  width: 100%;
  padding: 10px;
  border: 1px dashed var(--accent-color);
  border-radius: 8px;
  background: var(--accent-light);
  color: var(--accent-color);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.explain-btn:hover {
  background: var(--accent-color);
  color: #fff;
}

.explain-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  color: var(--text-muted);
  font-size: 13px;
}

.explain-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--accent-light);
  border-top-color: var(--accent-color);
  border-radius: 50%;
  animation: explain-spin 0.8s linear infinite;
}

@keyframes explain-spin {
  to { transform: rotate(360deg); }
}

.explain-error {
  padding: 10px;
  color: #c62828;
  font-size: 13px;
}

.explain-retry {
  margin-left: 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  padding: 3px 10px;
  cursor: pointer;
  font-size: 12px;
}

.ai-explanation {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--bg-secondary, #f8f9fb);
  font-size: 14px;
  line-height: 1.7;
}

.ai-explanation :deep(h2) { font-size: 15px; margin: 8px 0; }
.ai-explanation :deep(h3) { font-size: 14px; margin: 10px 0 4px; }
.ai-explanation :deep(p) { margin: 6px 0; }
.ai-explanation :deep(ul) { margin: 4px 0; padding-left: 18px; }

.question-stem {
  font-size: 14px;
  color: var(--text-primary);
  margin-bottom: 8px;
  line-height: 1.6;
}

.q-number {
  font-weight: 700;
  margin-right: 4px;
}

.q-type-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  margin-right: 4px;
}

.options-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.option-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.option-item:hover {
  border-color: var(--accent-color);
  background: var(--accent-light);
}

.option-item.selected {
  border-color: var(--accent-color);
  background: var(--accent-light);
}

.option-item.correct {
  border-color: #2e7d32;
  background: #e8f5e9;
}

.option-item.wrong {
  border-color: #c62828;
  background: #ffebee;
}

.option-key {
  font-weight: 600;
  width: 20px;
  text-align: center;
  color: var(--text-secondary);
}

.code-question, .open-question {
  margin-top: 8px;
}

.starter-code {
  background: var(--bg-code);
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 6px;
  overflow-x: auto;
}

.code-input, .open-input {
  width: 100%;
  min-height: 60px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  resize: vertical;
  background: var(--bg-input);
  color: var(--text-primary);
}

.explanation {
  margin-top: 8px;
  padding: 8px 12px;
  background: #e3f2fd;
  border-radius: 6px;
  font-size: 13px;
  color: #1565c0;
}

.quiz-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

.submit-btn {
  padding: 8px 32px;
  border: none;
  border-radius: 8px;
  background: var(--accent-color);
  color: white;
  font-size: 14px;
  cursor: pointer;
}

.submit-btn:hover {
  background: var(--accent-hover);
}

.score-display {
  display: flex;
  align-items: center;
  gap: 12px;
}

.score-text {
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.pass-badge {
  font-size: 14px;
  color: #059669;
}

.fail-badge {
  font-size: 14px;
  color: #dc2626;
}

.retry-btn {
  padding: 6px 16px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
