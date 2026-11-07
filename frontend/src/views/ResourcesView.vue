<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat'
import { getResources, getResourceDetail, submitPractice, completePathTopic } from '../api'
import MarkdownCard from '../components/resources/MarkdownCard.vue'
import MermaidViewer from '../components/resources/MermaidViewer.vue'
import NotebookViewer from '../components/resources/NotebookViewer.vue'
import QuizCard from '../components/resources/QuizCard.vue'

const chatStore = useChatStore()
const route = useRoute()
const router = useRouter()
const resources = ref([])
const loading = ref(true)
const filterType = ref('')
const onlyUnlearned = ref(false)
const mergedCount = ref(0)
// 主题筛选：从学习路径页「📚 学习资料」按钮跳转时带上（?topic=主题名）
const topicFilter = ref('')

// 只看未学筛选 + 统计
const visibleResources = computed(() => {
  let list = resources.value
  if (topicFilter.value) {
    const t = topicFilter.value
    list = list.filter(r =>
      (r.topic || '').includes(t) || (r.title || '').includes(t)
    )
  }
  return onlyUnlearned.value ? list.filter(r => !r.learned) : list
})
const allResources = computed(() => resources.value)
const learnedCount = computed(() => resources.value.filter(r => r.learned).length)

// 资源详情弹窗
const showDetail = ref(false)
const detailLoading = ref(false)
const currentResource = ref(null)

// 打开资料的时刻 → 用来估算实际学习时长。
// 之前这里写死 5 分钟，导致 learning_records.time_spent_minutes 变成常数，
// 让"学习投入度/推进速度"这些指标失真。
const detailOpenedAt = ref(0)
const MAX_SESSION_MINUTES = 120  // 防呆：标签页挂着不动不会记成几小时
function elapsedMinutes(fallback = 0) {
  if (!detailOpenedAt.value) return fallback
  const m = Math.round((Date.now() - detailOpenedAt.value) / 60000)
  return Math.min(MAX_SESSION_MINUTES, Math.max(1, m))
}

const typeLabels = {
  document: '📄 文档',
  mindmap: '🧠 导图',
  reading: '📖 阅读',
  quiz: '📝 题目',
  notebook: '💻 代码',
}

onMounted(async () => {
  // 从学习路径页跳过来时带的主题参数（?topic=...）
  topicFilter.value = (route.query.topic || '').toString()
  if (chatStore.sessionId) {
    await loadResources()
  }
  loading.value = false
})

// 已在资源页时再次点别的主题的「学习资料」→ 跟着新参数切筛选
watch(() => route.query.topic, (t) => {
  topicFilter.value = (t || '').toString()
})

// 清除主题筛选（筛选条上的 ✕）
function clearTopicFilter() {
  topicFilter.value = ''
  // 同步清掉地址栏参数，避免返回再进时又冒出来
  if (route.query.topic) router.replace({ query: {} })
}

// 空状态一键生成：跳到聊天页自动发一句"要资料"的话。
// 文案格式固定为「推荐一些学习资料：X」—— 主题放句尾，是因为 orchestrator 的 reading
// 规则要求"索取动词 + 资源名词"间隔 ≤15 字，主题名夹在中间（如"网络基础与 HTTP 协议"）
// 会超限漏判；放到冒号后面则无论多长都命中 reading，走 ReadingAgent 生成拓展阅读。
// 另：「我想学习：X」命中 learn 意图（AI 讲解 + 讲义），是「开始学习」按钮发的话，别混用。
const generating = ref(false)
function askGenerate() {
  const topic = topicFilter.value
  if (!topic) return
  generating.value = true
  chatStore.pendingMessage = `推荐一些学习资料：${topic}`
  router.push('/')
}

async function loadResources() {
  try {
    const data = await getResources(chatStore.sessionId, {
      type: filterType.value || undefined,
      size: 200,
    })
    resources.value = data.resources || []
    mergedCount.value = data.duplicates_merged || 0
  } catch (err) {
    console.error(err)
  }
}

async function openResource(res) {
  showDetail.value = true
  detailLoading.value = true
  currentResource.value = null
  detailOpenedAt.value = Date.now()  // 开始计时：用于"学完了"时估算实际用时
  // "学完了"按钮状态：历史上标记过就保持已按（不随弹窗重开复活）
  completeDone.value = resourceAlreadyDone(res)
  try {
    const detail = await getResourceDetail(chatStore.sessionId, res.resource_id)
    currentResource.value = detail
    if (resourceAlreadyDone(detail)) completeDone.value = true
  } catch (err) {
    console.error(err)
    currentResource.value = { ...res, content: '加载失败，请重试' }
  }
  detailLoading.value = false
}

// 该资源是否已标记过完成（对照持久化的"已完成主题"集合）
function resourceAlreadyDone(res) {
  if (!res) return false
  let parsed = null
  try { parsed = JSON.parse(res.content || '') } catch {}
  return chatStore.isTopicCompleted(chatStore.learningTopic)
    || chatStore.isTopicCompleted(parsed?.topic)
    || chatStore.isTopicCompleted(res.topic)
    || chatStore.isTopicCompleted(res.title)
}

function closeDetail() {
  showDetail.value = false
  currentResource.value = null
  detailOpenedAt.value = 0
}

function getTypeLabel(type) {
  return typeLabels[type] || '📦 资源'
}

function tryParseQuiz(content) {
  if (!content) return null
  try {
    const parsed = JSON.parse(content)
    if (parsed.questions || parsed.title) return parsed
  } catch {}
  return null
}

// 资源页做题提交后 → 写入学习记录（供学习评估使用）
async function handleQuizSubmitted({ correct, total }) {
  if (!chatStore.sessionId || !currentResource.value) return
  const res = currentResource.value
  const parsed = tryParseQuiz(res.content)
  // 优先用"正在学习的主题"（和学习路径主题名一致，通过后能直接标记路径完成）
  const topic = chatStore.learningTopic || parsed?.topic || res.topic || res.title || '练习'
  try {
    await submitPractice(chatStore.sessionId, {
      topic,
      correct,
      total,
      resource_id: res.resource_id || res.id || '',
      time_spent_minutes: elapsedMinutes(),  // 实际停留时长（拿不到则后端按题数估算）
    })
  } catch (err) {
    console.error('记录练习得分失败:', err)  // 静默失败，不影响做题体验
  }
}

// 看完资料（讲义/导图/代码）后手动标记"学完了" → 记入学习进度
const completing = ref(false)
const completeDone = ref(false)

async function markLearned() {
  if (!chatStore.sessionId || !currentResource.value) return
  const res = currentResource.value
  const parsed = tryParseQuiz(res.content)
  const topic = chatStore.learningTopic || parsed?.topic || res.topic || res.title
  completing.value = true
  try {
    await completePathTopic(chatStore.sessionId, {
      topic,
      resource_id: res.resource_id || res.id || '',
      // 实际停留时长；万一拿不到打开时刻，退回资料自带的预估分钟数
      time_spent_minutes: elapsedMinutes(res.metadata?.estimated_minutes || 5),
      self_evaluation: '资源页看完标记完成',
    })
    completeDone.value = true
    // 列表里对应卡片同步标记为已学完
    const hit = resources.value.find(r => r.resource_id === (res.resource_id || res.id))
    if (hit) hit.learned = true
    // 持久化"已完成"主题（让按钮不再复活）
    ;[topic, chatStore.learningTopic, parsed?.topic, res.topic, res.title].forEach(t => chatStore.markTopicCompleted(t))
  } catch (err) {
    console.error('记录学习进度失败:', err)
  }
  completing.value = false
}

function tryExtractMermaid(content) {
  if (!content) return ''
  return content
}
</script>

<template>
  <div class="resources-view">
    <div class="page-header">
      <h2>📚 学习资料库</h2>
      <p class="page-desc">按主题整理的学习资料 · 同一主题只保留最新一份 · 学完可一键记入学习进度</p>
    </div>

    <div class="filter-bar">
      <button v-if="topicFilter" class="topic-chip" :title="`只看主题包含「${topicFilter}」的资料`" @click="clearTopicFilter">
        📚 主题：{{ topicFilter }} ✕
      </button>
      <button :class="{ active: !filterType }" @click="filterType = ''; loadResources()">全部</button>
      <button v-for="(label, key) in typeLabels" :key="key"
        :class="{ active: filterType === key }"
        @click="filterType = key; loadResources()">{{ label }}</button>
      <button class="unlearned-toggle" :class="{ active: onlyUnlearned }" @click="onlyUnlearned = !onlyUnlearned">
        {{ onlyUnlearned ? '✓ 只看未学' : '只看未学' }}
      </button>
    </div>

    <div class="lib-summary" v-if="!loading && allResources.length > 0">
      共 {{ allResources.length }} 份资料<template v-if="mergedCount > 0">（已自动合并 {{ mergedCount }} 份重复）</template>，已学完 {{ learnedCount }} 份
    </div>

    <div v-if="loading">加载中...</div>

    <div v-else-if="visibleResources.length === 0" class="empty-state">
      <span class="empty-icon">📭</span>
      <p v-if="topicFilter">「{{ topicFilter }}」还没有学习资料</p>
      <p v-else-if="onlyUnlearned">🎉 未学的资料都学完了</p>
      <p v-else>还没有生成学习资源</p>
      <template v-if="topicFilter">
        <p class="empty-hint">资料是学习时 AI 生成的，这个主题还没学过，所以还没有。</p>
        <button class="gen-resource-btn" :disabled="generating" @click="askGenerate">
          {{ generating ? '⏳ 正在打开对话...' : `📖 去生成「${topicFilter}」的拓展阅读资料` }}
        </button>
      </template>
      <p class="empty-hint" v-else-if="onlyUnlearned">切回「全部」看看已学的资料</p>
      <p class="empty-hint" v-else>回到对话页面，告诉AI你想学什么</p>
    </div>

    <div v-else class="resource-grid">
      <div
        v-for="res in visibleResources"
        :key="res.resource_id"
        class="resource-card"
        :class="{ learned: res.learned }"
        @click="openResource(res)"
      >
        <div class="card-type-icon">{{ typeLabels[res.type]?.split(' ')[0] || '📦' }}</div>
        <div class="card-body">
          <div class="card-title-row">
            <span class="type-tag" :class="'type-' + res.type">{{ res.type_label || '资料' }}</span>
            <span class="card-title">{{ res.title }}</span>
            <span v-if="res.learned" class="learned-badge">已学完</span>
          </div>
          <div class="card-meta">
            <span v-if="res.topic && res.topic !== res.title">{{ res.topic }}</span>
            <span v-if="res.metadata?.difficulty">· {{ res.metadata.difficulty }}</span>
            <span v-if="res.metadata?.estimated_minutes">· 约{{ res.metadata.estimated_minutes }}分钟</span>
          </div>
        </div>
        <div v-if="res.user_rating" class="card-rating">⭐ {{ res.user_rating }}</div>
      </div>
    </div>

    <!-- 资源详情弹窗 -->
    <Teleport to="body">
      <div v-if="showDetail" class="modal-overlay" @click.self="closeDetail">
        <div class="modal-container">
          <div class="modal-header">
            <div class="modal-title-row">
              <span class="modal-type-icon">{{ getTypeLabel(currentResource?.type).split(' ')[0] }}</span>
              <div>
                <h3>{{ currentResource?.title || '资源详情' }}</h3>
                <span class="modal-meta">
                  {{ currentResource?.topic }} · {{ currentResource?.difficulty || '入门' }}
                </span>
              </div>
            </div>
            <button class="modal-close" @click="closeDetail">✕</button>
          </div>

          <div class="modal-body">
            <div v-if="detailLoading" class="modal-loading">加载中...</div>

            <!-- 文档/阅读 → Markdown 渲染 -->
            <MarkdownCard
              v-else-if="currentResource?.type === 'document' || currentResource?.type === 'reading'"
              :content="currentResource.content"
            />

            <!-- 思维导图 → Mermaid 渲染 -->
            <MermaidViewer
              v-else-if="currentResource?.type === 'mindmap'"
              :code="tryExtractMermaid(currentResource.content)"
            />

            <!-- 题目 → QuizCard -->
            <QuizCard
              v-else-if="currentResource?.type === 'quiz'"
              :data="tryParseQuiz(currentResource.content)"
              @quiz-submitted="handleQuizSubmitted"
            />

            <!-- 代码/Notebook → NotebookViewer -->
            <NotebookViewer
              v-else-if="currentResource?.type === 'notebook'"
              :content="currentResource.content"
            />

            <!-- 兜底：纯文本 -->
            <pre v-else class="raw-content">{{ currentResource?.content }}</pre>
          </div>

          <!-- 底部：标记完成（题目资源除外——做题交卷会自动记） -->
          <div v-if="currentResource?.type !== 'quiz' && !detailLoading" class="modal-footer">
            <button
              class="learned-btn"
              :class="{ done: completeDone }"
              :disabled="completing || completeDone"
              @click="markLearned"
            >
              {{ completeDone ? '✅ 已记入学习进度' : completing ? '记录中...' : '✅ 学完了，记入学习进度' }}
            </button>
            <span v-if="completeDone" class="footer-hint">去「学习路径」页查看解锁的新内容</span>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.resources-view {
  max-width: 900px;
  margin: 0 auto;
  padding-bottom: 40px;
}

.page-header {
  margin-bottom: 16px;
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

.filter-bar {
  display: flex;
  gap: 6px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.unlearned-toggle {
  margin-left: auto;
}

.lib-summary {
  font-size: 12px;
  color: var(--text-muted);
  margin: -10px 0 14px;
}

.filter-bar button {
  padding: 6px 14px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.15s;
}

.filter-bar button:hover {
  border-color: var(--accent-color);
  color: var(--accent-color);
}

.filter-bar button.active {
  background: var(--accent-color);
  color: white;
  border-color: var(--accent-color);
}

/* 主题筛选条（从学习路径页跳转时出现） */
.filter-bar .topic-chip {
  border-color: var(--accent-color);
  color: var(--accent-color);
  background: var(--accent-light, #eef2ff);
  font-weight: 600;
}

.filter-bar .topic-chip:hover {
  background: var(--accent-color);
  color: white;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 40px;
}

.empty-hint {
  font-size: 13px;
}

/* 空状态里的"去生成"按钮（主题筛选下没有资料时） */
.gen-resource-btn {
  margin-top: 14px;
  padding: 9px 22px;
  border: none;
  border-radius: 8px;
  background: var(--accent-color);
  color: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.gen-resource-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.gen-resource-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.resource-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  background: var(--bg-primary);
}

.resource-card:hover {
  border-color: var(--accent-color);
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.card-type-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.card-body {
  flex: 1;
  min-width: 0;
}

/* 资料类型标签：同一主题可能有讲义+练习题，靠它区分 */
.type-tag {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  vertical-align: middle;
  background: #eef2ff;
  color: #4f46e5;
  border: 1px solid #e0e7ff;
}
.type-tag.type-quiz { background: #fff7ed; color: #c2410c; border-color: #ffedd5; }
.type-tag.type-mindmap { background: #f5f3ff; color: #7c3aed; border-color: #ede9fe; }
.type-tag.type-notebook { background: #ecfdf5; color: #047857; border-color: #d1fae5; }
.type-tag.type-reading { background: #f0f9ff; color: #0369a1; border-color: #e0f2fe; }

.resource-card.learned .type-tag {
  opacity: 0.65;
}

/* 标题行：标签和徽章固定显示，只有标题文字可被截断（否则长标题会把徽章挤出视野） */
.card-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.card-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.learned-badge {
  flex-shrink: 0;
}

.resource-card.learned {
  background: var(--bg-hover);
  border-color: transparent;
}

.resource-card.learned .card-title {
  color: var(--text-muted);
}

.learned-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  background: #dcfce7;
  color: #16a34a;
  font-size: 11px;
  font-weight: 600;
  vertical-align: middle;
}

.card-meta {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.card-rating {
  font-size: 12px;
  color: #f59e0b;
  flex-shrink: 0;
}

/* ====== 弹窗样式 ====== */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 1000;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 40px 20px;
  overflow-y: auto;
}

.modal-container {
  background: var(--bg-primary);
  border-radius: 14px;
  width: 100%;
  max-width: 820px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 12px 40px rgba(0,0,0,0.15);
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.modal-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.modal-type-icon {
  font-size: 28px;
}

.modal-header h3 {
  margin: 0 0 4px;
  font-size: 18px;
  color: var(--text-primary);
}

.modal-meta {
  font-size: 12px;
  color: var(--text-muted);
}

.modal-close {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--border-color);
  background: transparent;
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: all 0.15s;
  flex-shrink: 0;
}

.modal-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.modal-body {
  padding: 20px 24px 24px;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  border-top: 1px solid var(--border-color);
}

.learned-btn {
  padding: 8px 20px;
  border-radius: 8px;
  border: 1px solid var(--accent-color);
  background: var(--accent-color);
  color: white;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.learned-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.learned-btn.done {
  background: #f0fdf4;
  border-color: #a5d6a7;
  color: #059669;
  cursor: default;
}

.footer-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.modal-loading {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
}

.raw-content {
  white-space: pre-wrap;
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.6;
}
</style>
