<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat'
import { usePathStore } from '../stores/path'
import { getLearningPath, getRecommendations, startPractice, submitPractice, startTopic, getResources, getWrongQuestions, resolveWrongQuestion, explainMistakes } from '../api'
import PathTimeline from '../components/path/PathTimeline.vue'
import TopicCard from '../components/path/TopicCard.vue'
import QuizCard from '../components/resources/QuizCard.vue'
import ResourceLoader from '../components/resources/ResourceLoader.vue'

const router = useRouter()
const chatStore = useChatStore()
const pathStore = usePathStore()
const loading = ref(true)
const practicingTopic = ref(null)      // 当前正在练习的主题名
const practiceQuiz = ref(null)          // 题目数据
const practiceLoading = ref(false)      // 题目生成中
const practiceResult = ref(null)        // { passed, score_pct, message }
const practiceTopicTitle = ref('')      // 当前练习的主题标题
const quizCardRef = ref(null)            // QuizCard 组件引用
const currentPracticeTopic = ref(null)   // 当前练习的 topic 对象（"换一批"用）

// ── 三步完成标记 ──
// 一个主题要"开始学习 → 看学习资料 → 练练手通过（≥60%）"三步都走完才算完成，
// 但按钮做完后样式不变，只有整行变淡，用户根本看不出还差哪一步。
// 现在每一步做完，对应的按钮就变绿打勾。
// 其中"学习资料看过没有"后端没有记录，点进资料库即视为看过，
// 记在 localStorage（刷新/重进不丢）。
const RESOURCE_VIEWED_KEY = 'resourceViewedTopics'
function _loadViewedTopics() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RESOURCE_VIEWED_KEY) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    // 本地数据损坏时不要让页面挂掉，清掉重来
    localStorage.removeItem(RESOURCE_VIEWED_KEY)
    return []
  }
}
const viewedTopics = ref(_loadViewedTopics())

function markResourceViewed(title) {
  if (!title || viewedTopics.value.includes(title)) return
  viewedTopics.value.push(title)
  localStorage.setItem(RESOURCE_VIEWED_KEY, JSON.stringify(viewedTopics.value))
}

// 各主题已有几份学习资料（topic → 份数）。
// 「📚 学习资料」按钮靠它决定：有资料就进资料库看，没有就直接去生成，
// 免得点进去是个空页面（资料是学的时候才生成的，没学过的主题必然没有）。
const resourceCounts = ref({})

function resourceCountOf(topicTitle) {
  if (!topicTitle) return 0
  let n = 0
  for (const [t, c] of Object.entries(resourceCounts.value)) {
    // 和资料库的筛选口径一致：资料主题包含该主题名即算
    if (t.includes(topicTitle)) n += c
  }
  return n
}

async function loadResourceCounts() {
  try {
    const data = await getResources(chatStore.sessionId, { size: 200 })
    const counts = {}
    for (const r of data.resources || []) {
      const t = ((r.topic || r.title) || '').trim()
      if (!t) continue
      counts[t] = (counts[t] || 0) + 1
    }
    resourceCounts.value = counts
  } catch (err) {
    console.error('加载资料统计失败:', err)  // 拿不到就退化为不显示数量，不影响主流程
  }
}

// ── 错题本 / 复习清单 ──
const wrongQuestions = ref([])
const wrongLoading = ref(false)
const explainingId = ref(null)      // 正在 AI 讲解的错题 id
const explainedHtml = ref({})       // id → 讲解 HTML（marked 渲染后）
const resolvingId = ref(null)

async function loadWrongQuestions() {
  if (!chatStore.sessionId) return
  wrongLoading.value = true
  try {
    const data = await getWrongQuestions(chatStore.sessionId)
    wrongQuestions.value = data.wrong_questions || []
  } catch (err) {
    console.error('加载错题本失败:', err)   // 失败不打扰主流程
  } finally {
    wrongLoading.value = false
  }
}

// 复习清单里的 AI 讲解（单题版，复用 explain-mistakes 接口）
async function explainWrong(q) {
  if (explainedHtml.value[q.id]) {   // 已讲过 → 再点收起
    const copy = { ...explainedHtml.value }
    delete copy[q.id]
    explainedHtml.value = copy
    return
  }
  explainingId.value = q.id
  try {
    const res = await explainMistakes(chatStore.sessionId, q.topic || '', [{
      stem: q.stem,
      options: q.options || [],
      answer: q.answer,
      user_answer: q.user_answer,
      explanation: q.explanation || '',
    }])
    const { marked } = await import('marked')
    let html = ''
    try { html = marked.parse(res.explanation || '') } catch { html = res.explanation || '' }
    explainedHtml.value = { ...explainedHtml.value, [q.id]: html }
  } catch (err) {
    alert(err.message || '讲解生成失败，请重试')
  } finally {
    explainingId.value = null
  }
}

// 「我掌握了」→ 从复习清单移除
async function markResolved(q) {
  resolvingId.value = q.id
  try {
    await resolveWrongQuestion(chatStore.sessionId, q.id)
    wrongQuestions.value = wrongQuestions.value.filter(w => w.id !== q.id)
  } catch (err) {
    alert(err.message || '操作失败')
  } finally {
    resolvingId.value = null
  }
}

// step: 'start' | 'material' | 'practice'
function stepDone(topic, step) {
  const status = topic.status
  if (step === 'start') return status === 'in_progress' || status === 'completed'
  if (step === 'material') return viewedTopics.value.includes(topic.title) || status === 'completed'
  if (step === 'practice') return status === 'completed'
  return false
}

// ── 学习计时：开始学习 → 练练手完成 ──
const STUDY_TIMER_KEY = 'study_timer_start'

// 从 phases 中收集所有 topic
const allTopics = computed(() => {
  const topics = []
  for (const phase of pathStore.phases) {
    if (phase.topics) {
      for (const t of phase.topics) {
        topics.push({ ...t, phaseOrder: phase.order, phaseTitle: phase.title })
      }
    } else {
      // 没有子 topic，phase 本身就是 topic
      topics.push({
        topic_id: `phase_${phase.order}`,
        title: phase.title,
        status: phase.status,
        phaseOrder: phase.order,
        phaseTitle: phase.title,
      })
    }
  }
  return topics
})

// 统计进度
const progressStats = computed(() => {
  const topics = allTopics.value
  const completed = topics.filter(t => t.status === 'completed').length
  const available = topics.filter(t => t.status === 'available' || t.status === 'in_progress').length
  const total = topics.length
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0
  return { completed, available, total, pct }
})

onMounted(async () => {
  if (!chatStore.sessionId) {
    loading.value = false
    return
  }

  try {
    const [pathData, recData] = await Promise.all([
      getLearningPath(chatStore.sessionId),
      getRecommendations(chatStore.sessionId, 5),
    ])
    pathStore.setPath(pathData)
    pathStore.setRecommendations(recData)
    await loadResourceCounts()   // 各主题有几份资料（"学习资料"按钮用）
    loadWrongQuestions()         // 复习清单
  } catch (err) {
    console.error(err)
  }
  loading.value = false
})

// 开始在聊天中学习某个主题 — 记录开始时间
async function startLearning(topic) {
  // 将开始时间存入 sessionStorage（跨页面保持）
  sessionStorage.setItem(STUDY_TIMER_KEY, JSON.stringify({
    topic: topic.title,
    start: Date.now(),
  }))
  chatStore.pendingTopic = topic.title
  chatStore.setLearningTopic(topic.title)  // 聊天里说"完成了"时可自动记进度
  // 通知后端「已开始学习」；若此前练练手已通过，后端会直接补成已完成
  try {
    await startTopic(chatStore.sessionId, topic.title)
    // 本地立刻同步状态，从聊天页返回时按钮已经变绿，不用等重新拉路径
    const topicKey = topic.topic_id || topic.title
    for (const phase of pathStore.phases) {
      for (const t of phase.topics || []) {
        if ((t.topic_id || t.title) === topicKey && t.status === 'available') {
          t.status = 'in_progress'
        }
      }
      if ((`phase_${phase.order}` === topicKey || phase.title === topic.title) && phase.status === 'available') {
        phase.status = 'in_progress'
      }
    }
  } catch (e) {
    console.error('标记开始学习失败:', e)
  }
  router.push('/')
}

// 练练手 — 开始练习（force=true 表示"换一批"，强制重新生成；否则优先复用秒开）
async function beginPractice(topic, force = false) {
  practiceTopicTitle.value = topic.title
  practicingTopic.value = topic.topic_id || topic.title
  currentPracticeTopic.value = topic
  practiceQuiz.value = null
  practiceResult.value = null
  practiceLoading.value = true

  // 用户直接点「练练手」（没先点过「开始学习」）时，从这里开始计时。
  // 已有同主题的计时则不覆盖——免得抹掉"开始学习"之后那段看资料的时间。
  try {
    const raw = sessionStorage.getItem(STUDY_TIMER_KEY)
    const t = raw ? JSON.parse(raw) : null
    if (!t || t.topic !== topic.title) {
      sessionStorage.setItem(STUDY_TIMER_KEY, JSON.stringify({
        topic: topic.title,
        start: Date.now(),
      }))
    }
  } catch {}

  try {
    const quizData = await startPractice(chatStore.sessionId, topic.title, force)
    practiceQuiz.value = quizData
  } catch (err) {
    console.error('生成练习失败:', err)
    practiceResult.value = { passed: false, score_pct: 0, message: '题目生成失败，请重试' }
  }
  practiceLoading.value = false
}

// 练练手 — 提交答案
async function handleQuizSubmit({ correct, total, mistakes }) {
  const topicName = practiceTopicTitle.value

  // 从 sessionStorage 读取计时：点过"开始学习"/"练练手"用实际跨度，否则默认 5 分钟
  let elapsedMin = 5  // 默认值
  try {
    const raw = sessionStorage.getItem(STUDY_TIMER_KEY)
    if (raw) {
      const timer = JSON.parse(raw)
      // 只匹配同一个 topic
      if (timer.topic === topicName) {
        // 上限 120 分钟：标签页挂着不动不会记成几小时
        elapsedMin = Math.min(120, Math.max(1, Math.round((Date.now() - timer.start) / 60000)))
      }
    }
  } catch {}
  sessionStorage.removeItem(STUDY_TIMER_KEY)  // 用后即清

  try {
    const result = await submitPractice(chatStore.sessionId, {
      topic: topicName,
      correct,
      total,
      resource_id: practiceQuiz.value?.resource_id || '',
      time_spent_minutes: elapsedMin,
      mistakes: mistakes || [],   // 错题明细 → 后端错题本
    })
    practiceResult.value = result
    loadWrongQuestions()   // 刚做的错题立刻出现在复习清单里

    // 通过 → 更新本地状态
    if (result.passed && result.path_updated) {
      const topicKey = practicingTopic.value
      for (const phase of pathStore.phases) {
        if (phase.topics) {
          for (const t of phase.topics) {
            if ((t.topic_id || t.title) === topicKey) {
              t.status = 'completed'
            }
          }
        }
        if (`phase_${phase.order}` === topicKey || phase.title === topicName) {
          phase.status = 'completed'
        }
      }
      // 自动解锁下一个
      for (let pi = 0; pi < pathStore.phases.length; pi++) {
        const phase = pathStore.phases[pi]
        const topics = phase.topics || []
        for (let i = 0; i < topics.length; i++) {
          if ((topics[i].topic_id || topics[i].title) === topicKey) {
            if (i + 1 < topics.length) {
              if (topics[i + 1].status === 'locked') topics[i + 1].status = 'available'
            } else {
              // 本阶段最后一个完成 → 解锁下一个阶段的第一个主题（严格串行）
              for (const np of pathStore.phases.slice(pi + 1)) {
                if (np.topics && np.topics.length) {
                  if (np.topics[0].status === 'locked') {
                    np.topics[0].status = 'available'
                    np.status = 'available'
                  }
                  break
                }
              }
            }
            break
          }
        }
      }
    }
  } catch (err) {
    console.error('提交练习失败:', err)
    practiceResult.value = { passed: false, score_pct: 0, message: '提交失败，请重试' }
  }
}

// 关闭练习弹窗
function closePractice() {
  practicingTopic.value = null
  practiceQuiz.value = null
  practiceResult.value = null
  practiceTopicTitle.value = ''
}

// 跳到学习资料库，自动按该主题筛选
function goResources(topic) {
  markResourceViewed(topic.title)   // 点进去看就算这一步完成了
  router.push({ path: '/resources', query: { topic: topic.title } })
}

// 这个主题还没有资料 → 直接去生成，而不是跳到空页面。
// 消息走「推荐一些X的学习资料」而不是「我想学习：X」——
// 后者是"开始学习"按钮发的话，两者必须不一样：
// 「我想学习」命中 learn 意图（AI 讲解 + 生成讲义），
// 「推荐…学习资料」命中 reading 意图（ReadingAgent 生成拓展阅读/资料清单）。
function generateMaterial(topic) {
  chatStore.pendingMessage = `推荐一些学习资料：${topic.title}`
  router.push('/')
}

// 「📚 学习资料」：有资料就看，没有就直接去生成
function onMaterialClick(topic) {
  if (resourceCountOf(topic.title) > 0) {
    goResources(topic)
  } else {
    generateMaterial(topic)
  }
}

// 悬停说明：区分"有资料去看"和"没资料去生成"
function materialTitle(topic) {
  const n = resourceCountOf(topic.title)
  if (stepDone(topic, 'material')) return '已查看过该主题的学习资料'
  if (n > 0) return `查看该主题已生成的 ${n} 份资料`
  return '这个主题还没有资料，点击去生成一份拓展阅读'
}

// 空状态：跳到聊天页并自动发送路径规划请求
const generating = ref(false)
function generatePath() {
  generating.value = true
  chatStore.pendingMessage = '帮我规划一条学习路径'
  router.push('/')
}

// 重新作答（不重新生成题目，用已保存的）
function retryPractice() {
  practiceResult.value = null
  quizCardRef.value?.resetQuiz()
}
</script>

<template>
  <div class="path-view">
    <div class="page-header">
      <h2>🗺️ 学习路径</h2>
      <p class="page-desc">基于你的画像动态规划的学习路线</p>
    </div>

    <div v-if="loading" class="empty-state">
      <div class="empty-icon">🗺️</div>
      <p>正在加载你的学习路径...</p>
    </div>

    <div v-else-if="allTopics.length === 0" class="empty-state">
      <div class="empty-icon">🧭</div>
      <h3>还没有学习路径</h3>
      <p class="empty-desc">
        和 AI 聊聊你想学什么，它会根据你的水平和目标，
        <br />为你定制一条循序渐进的学习路线。
      </p>
      <button class="generate-btn" :disabled="generating" @click="generatePath">
        {{ generating ? '⏳ 正在打开对话...' : '🎯 为我生成学习路径' }}
      </button>
      <p class="empty-tip">小技巧：也可以直接在聊天里说「帮我规划学习路径」</p>
    </div>

    <div v-else>
      <!-- 进度概览 -->
      <div v-if="progressStats.total > 0" class="progress-overview">
        <div class="progress-bar-wrapper">
          <div class="progress-bar" :style="{ width: `${progressStats.pct}%` }"></div>
        </div>
        <div class="progress-text">
          已完成 {{ progressStats.completed }}/{{ progressStats.total }} 个主题（{{ progressStats.pct }}%）
        </div>
      </div>

      <!-- 错题本 / 复习清单 -->
      <div v-if="wrongQuestions.length > 0" class="review-panel">
        <h3>🔁 复习清单 <span class="review-count">{{ wrongQuestions.length }}</span></h3>
        <p class="steps-hint">这些是你做错过的题，重做做对或点「掌握了」就会从清单移除。错得越多越靠前。</p>
        <div v-for="q in wrongQuestions" :key="q.id" class="review-item">
          <div class="review-head" @click="explainWrong(q)">
            <span class="review-wrong-count" :title="`做错了 ${q.wrong_count} 次`">×{{ q.wrong_count }}</span>
            <span class="review-stem">{{ q.stem }}</span>
            <span class="review-topic">{{ q.topic }}</span>
          </div>
          <div class="review-meta">
            你的答案 <b class="ans-wrong">{{ q.user_answer || '未作答' }}</b>
            · 正确答案 <b class="ans-right">{{ q.answer }}</b>
            <button class="review-btn explain" @click.stop="explainWrong(q)">
              {{ explainingId === q.id ? '⏳ AI 分析中…' : (explainedHtml[q.id] ? '▲ 收起讲解' : '🤖 AI 讲解') }}
            </button>
            <button class="review-btn resolve" :disabled="resolvingId === q.id" @click.stop="markResolved(q)">
              ✓ 我掌握了
            </button>
          </div>
          <div v-if="explainedHtml[q.id]" class="review-explanation" v-html="explainedHtml[q.id]"></div>
        </div>
      </div>

      <PathTimeline
        :phases="pathStore.phases"
        :recommended-next="pathStore.recommendedNext"
      />

      <!-- 主题操作面板 -->
      <div v-if="allTopics.length > 0" class="topics-panel">
        <h3>📋 学习任务清单</h3>
        <p class="steps-hint">
          每个主题三步走：💬 开始学习 → 📚 学习资料 → 🏋️ 练练手（答对 ≥60%）。
          完成一步，按钮就变绿并打勾；三步全绿才算学完这个主题。
        </p>
        <div
          v-for="topic in allTopics"
          :key="topic.topic_id || topic.title"
          class="topic-row"
          :class="{ completed: topic.status === 'completed' }"
        >
          <span class="topic-status-icon">
            {{ topic.status === 'completed' ? '✅' : topic.status === 'locked' ? '🔒' : '📖' }}
          </span>
          <div class="topic-info">
            <span class="topic-name">{{ topic.title }}</span>
            <span class="topic-phase">{{ topic.phaseTitle }}</span>
          </div>
          <!-- 三步：开始学习 → 学习资料 → 练练手。
               每完成一步，对应的按钮变绿打勾；三步都绿，主题才算完成。 -->
          <div class="topic-actions">
            <button
              v-if="topic.status !== 'locked'"
              class="action-btn start"
              :class="{ done: stepDone(topic, 'start') }"
              :title="stepDone(topic, 'start') ? '已开始学习这个主题，可继续' : '进入对话开始学习这个主题'"
              @click="startLearning(topic)"
            >
              {{ stepDone(topic, 'start') ? '✓ 💬 开始学习' : '💬 开始学习' }}
            </button>
            <!-- 学习资料：已有资料就进资料库看，还没有就直接去生成一份 -->
            <button
              v-if="topic.status !== 'locked'"
              class="action-btn material"
              :class="{ done: stepDone(topic, 'material') }"
              :title="materialTitle(topic)"
              @click="onMaterialClick(topic)"
            >
              {{ stepDone(topic, 'material') ? '✓ 📚 学习资料' : '📚 学习资料' }}<span
                v-if="resourceCountOf(topic.title)"
                class="btn-count"
              >{{ resourceCountOf(topic.title) }}</span>
            </button>
            <!-- 练练手：通过后再练也保留，想练就练（放在最后一个） -->
            <button
              v-if="topic.status !== 'locked'"
              class="action-btn practice"
              :class="{ done: stepDone(topic, 'practice') }"
              :title="stepDone(topic, 'practice') ? '练练手已通过（≥60%），可再练' : '做题检验，答对 ≥60% 才算通过'"
              @click="beginPractice(topic)"
            >
              {{ stepDone(topic, 'practice') ? '✓ 🏋️ 练练手' : '🏋️ 练练手' }}
            </button>
            <span v-if="topic.status === 'completed'" class="done-label">已完成</span>
          </div>
        </div>
      </div>

      <div v-if="pathStore.recommendations.length > 0" class="recommendations-section">
        <h3>📌 为你推荐</h3>
        <div class="rec-grid">
          <TopicCard
            v-for="rec in pathStore.recommendations"
            :key="rec.resource_id"
            :topic="rec"
            :status="'in_progress'"
          />
        </div>
      </div>

      <!-- 练练手弹窗 -->
      <div v-if="practicingTopic" class="practice-overlay" @click.self="closePractice">
        <div class="practice-modal">
          <div class="practice-modal-header">
            <h3>🏋️ 练练手 — {{ practiceTopicTitle }}</h3>
            <span class="pass-line">通过线: 60%</span>
            <button
              v-if="practiceQuiz && !practiceLoading"
              class="swap-btn"
              title="重新生成一套新题（约需 5~10 秒）"
              @click="beginPractice(currentPracticeTopic, true)"
            >🔄 换一批</button>
            <button class="close-btn" @click="closePractice">✕</button>
          </div>

          <!-- 加载中 -->
          <div v-if="practiceLoading" class="practice-loading">
            <ResourceLoader type="quiz" title="正在生成练习题" />
          </div>

          <!-- 题目 -->
          <div v-else-if="practiceQuiz" class="practice-quiz-wrapper">
            <QuizCard
              ref="quizCardRef"
              :data="practiceQuiz"
              :on-submitted="handleQuizSubmit"
              @quiz-submitted="handleQuizSubmit"
            />
          </div>

          <!-- 结果提示（未通过） -->
          <div v-if="practiceResult && !practiceResult.passed && !practiceLoading" class="practice-result fail">
            <p>{{ practiceResult.message }}</p>
            <button class="retry-btn" @click="retryPractice">🔄 重新作答</button>
          </div>

          <!-- 结果提示（通过） -->
          <div v-if="practiceResult && practiceResult.passed" class="practice-result pass">
            <p>🎉 {{ practiceResult.message }}</p>
            <button class="close-practice-btn" @click="closePractice">关闭</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.path-view {
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

/* 进度条 */
.progress-overview {
  margin-bottom: 20px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-primary);
}

.progress-bar-wrapper {
  height: 8px;
  background: var(--bg-hover);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-color), #34d399);
  border-radius: 4px;
  transition: width 0.5s ease;
}

.progress-text {
  font-size: 13px;
  color: var(--text-secondary);
}

/* 任务清单 */
.topics-panel {
  margin-top: 24px;
}

.topics-panel h3 {
  font-size: 16px;
  color: var(--text-primary);
  margin: 0 0 12px;
}

.topic-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  margin-bottom: 8px;
  background: var(--bg-primary);
  transition: all 0.15s;
}

.topic-row.completed {
  background: #f5fdf5;
  border-color: #bbf7d0;
}

/* 整行不再整体变淡 —— 淡了以后绿色打勾看不清，
   改成只把标题染绿，完成感反而更明确 */
.topic-row.completed .topic-name {
  color: #2e7d32;
}

.topic-status-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.topic-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topic-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.topic-phase {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.topic-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.action-btn {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-secondary);
  transition: all 0.15s;
  white-space: nowrap;
}

.action-btn.start {
  border-color: var(--accent-color);
  color: var(--accent-color);
}

.action-btn.start:hover {
  background: var(--accent-light);
}

.action-btn.practice {
  border-color: #f59e0b;
  color: #d97706;
}

.action-btn.practice:hover {
  background: #fffbeb;
}

.action-btn.material {
  border-color: #3b82f6;
  color: #2563eb;
}

.action-btn.material:hover {
  background: #eff6ff;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 这一步已完成 → 变绿打勾，让"还差哪一步"一眼可见 */
.action-btn.done {
  border-color: #34d399;
  color: #059669;
  background: #ecfdf5;
}

.action-btn.done:hover {
  background: #d1fae5;
  border-color: #10b981;
}

.steps-hint {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
  margin: 0 0 12px;
}

/* 「学习资料」按钮上的资料份数角标（0 份时不显示） */
.btn-count {
  display: inline-block;
  margin-left: 4px;
  min-width: 14px;
  padding: 0 4px;
  border-radius: 7px;
  background: currentColor;
  color: var(--bg-primary);
  font-size: 10px;
  line-height: 15px;
  font-weight: 600;
  text-align: center;
  vertical-align: middle;
}

.done-label {
  font-size: 12px;
  color: #059669;
  font-weight: 500;
}

.recommendations-section {
  margin-top: 24px;
}

.recommendations-section h3 {
  font-size: 16px;
  color: var(--text-primary);
  margin: 0 0 12px;
}

.rec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}

/* 复习清单（错题本） */
.review-panel {
  margin-top: 20px;
  padding: 14px 16px;
  border: 1px solid #fecaca;
  border-radius: 10px;
  background: #fff7f7;
}

.review-panel h3 {
  font-size: 16px;
  color: var(--text-primary);
  margin: 0 0 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.review-count {
  font-size: 12px;
  background: #dc2626;
  color: #fff;
  min-width: 18px;
  padding: 1px 6px;
  border-radius: 9px;
  text-align: center;
}

.review-item {
  padding: 10px 0;
  border-bottom: 1px dashed #fecaca;
}

.review-item:last-child {
  border-bottom: none;
}

.review-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  cursor: pointer;
}

.review-wrong-count {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: #b91c1c;
  background: #fee2e2;
  padding: 1px 6px;
  border-radius: 8px;
}

.review-stem {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
}

.review-topic {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-muted);
}

.review-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
  padding-left: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}

.ans-wrong { color: #dc2626; }
.ans-right { color: #059669; }

.review-btn {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-secondary);
  transition: all 0.15s;
}

.review-btn.explain {
  border-color: var(--accent-color);
  color: var(--accent-color);
}

.review-btn.explain:hover {
  background: var(--accent-light);
}

.review-btn.resolve {
  border-color: #34d399;
  color: #059669;
}

.review-btn.resolve:hover {
  background: #ecfdf5;
}

.review-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.review-explanation {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
  font-size: 13px;
  line-height: 1.7;
}

.review-explanation :deep(h2) { font-size: 14px; margin: 6px 0; }
.review-explanation :deep(h3) { font-size: 13px; margin: 8px 0 4px; }
.review-explanation :deep(p) { margin: 4px 0; }

/* 移动端：主题行的三个按钮放不下时换行到下一行，避免横向溢出 */
@media (max-width: 640px) {
  .topic-row {
    flex-wrap: wrap;
  }

  .topic-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .practice-modal {
    width: 96%;
    max-height: 92vh;
  }

  .review-head {
    flex-wrap: wrap;
  }
}

/* 练习弹窗 */
.practice-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.practice-modal {
  background: var(--bg-primary);
  border-radius: 12px;
  width: 90%;
  max-width: 700px;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.practice-modal-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  z-index: 1;
}

.practice-modal-header h3 {
  flex: 1;
  font-size: 16px;
  margin: 0;
  color: var(--text-primary);
}

.pass-line {
  font-size: 12px;
  color: #d97706;
  background: #fffbeb;
  padding: 3px 10px;
  border-radius: 10px;
  border: 1px solid #fcd34d;
}

.swap-btn {
  background: #fff;
  border: 1px solid var(--border-color);
  font-size: 12px;
  cursor: pointer;
  color: var(--text-secondary, #555);
  padding: 3px 10px;
  border-radius: 10px;
  white-space: nowrap;
}

.swap-btn:hover {
  background: var(--bg-hover);
  border-color: var(--accent-color);
  color: var(--accent-color);
}

.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: var(--text-muted);
  padding: 4px 8px;
  border-radius: 4px;
}

.close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.practice-loading {
  padding: 40px;
  text-align: center;
  color: var(--text-muted);
}

.practice-quiz-wrapper {
  padding: 0;
}

.practice-quiz-wrapper :deep(.quiz-card) {
  border: none;
  margin: 0;
  border-radius: 0;
}

.practice-result {
  padding: 20px;
  text-align: center;
  border-top: 1px solid var(--border-color);
}

.practice-result.pass {
  background: #f0fdf4;
}

.practice-result.fail {
  background: #fef2f2;
}

.practice-result p {
  font-size: 15px;
  margin: 0 0 14px;
  color: var(--text-primary);
}

.retry-btn, .close-practice-btn {
  padding: 8px 24px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  color: var(--text-primary);
  transition: all 0.15s;
}

.retry-btn:hover, .close-practice-btn:hover {
  background: var(--bg-hover);
}
</style>
