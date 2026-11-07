<script setup>
import { computed, onMounted, ref } from 'vue'
import MarkdownCard from '../resources/MarkdownCard.vue'
import MermaidViewer from '../resources/MermaidViewer.vue'
import NotebookViewer from '../resources/NotebookViewer.vue'
import QuizCard from '../resources/QuizCard.vue'
import ResourceLoader from '../resources/ResourceLoader.vue'
import { useChatStore } from '../../stores/chat'
import { submitPractice, completePathTopic } from '../../api'

const props = defineProps({
  message: Object,
})

const chatStore = useChatStore()

// 这条消息出现的时刻 → 用来估算实际学习时长。
// 之前"我学完了"写死 5 分钟，让 learning_records.time_spent_minutes 变成常数，
// 使"学习投入度/推进速度"等指标失真。
const mountedAt = ref(0)
onMounted(() => { mountedAt.value = Date.now() })
const MAX_SESSION_MINUTES = 120  // 防呆：页面挂着不动不会记成几小时
function elapsedMinutes(fallback = 0) {
  if (!mountedAt.value) return fallback
  const m = Math.round((Date.now() - mountedAt.value) / 60000)
  return Math.min(MAX_SESSION_MINUTES, Math.max(1, m))
}

// 聊天里做的练习题提交后 → 写入学习记录（供学习评估使用）
async function handleQuizSubmitted({ correct, total }) {
  if (!chatStore.sessionId) return
  // 优先用"正在学习的主题"（和学习路径主题名一致，做对了能直接标记路径完成），
  // 没有再用题目自带的话题
  const topic = chatStore.learningTopic || quizData.value?.topic || quizData.value?.title || '聊天练习'
  try {
    await submitPractice(chatStore.sessionId, {
      topic,
      correct,
      total,
      resource_id: props.message.resourceId || props.message.resource_id || '',
      time_spent_minutes: elapsedMinutes(),  // 实际停留时长（拿不到则后端按题数估算）
    })
  } catch (err) {
    console.error('记录练习得分失败:', err)  // 静默失败，不影响做题体验
  }
}

// 看完聊天里的学习资源后，一键标记"学完了"（不用打字，不识字也能点）
const completing = ref(false)

// 讲义类长文档识别（刷新后历史消息没有 resourceType 标记，靠内容结构判断）：
// 足够长 + 有 H1 标题或多个 H2 小节，才认定为学习资料
const isLectureLike = computed(() => {
  const content = props.message.content || ''
  if (content.length < 500) return false
  const hasH1 = /^#\s+\S/m.test(content)
  const h2Count = (content.match(/^##\s+/gm) || []).length
  return hasH1 || h2Count >= 3
})

const isResourceMsg = computed(() => {
  return !isUser.value && !isStreaming.value && Boolean(
    props.message.resourceType || isMermaid.value || isNotebook.value || isQuiz.value || isLectureLike.value
  )
})

// 主题优先级：正在学的主题 > 从资源标题/内容首行猜 > 兜底
const guessedTopic = computed(() => {
  if (chatStore.learningTopic) return chatStore.learningTopic
  const m = headingGuess()
  if (m) return m
  return '聊天学习'
})

// 从内容首个 markdown 标题/加粗行提取主题（去掉"讲义："等前缀）
function headingGuess() {
  const content = (props.message.content || '').trim()
  const m = content.match(/^#{1,3}\s*(.+)$/m) || content.match(/^\*\*(.+?)\*\*/)
  if (m) {
    return m[1].replace(/^(讲义|思维导图|导图|题目|练习|代码|笔记)[：:]\s*/, '').slice(0, 30)
  }
  return ''
}

// 是否已记过进度（本次会话点过 or 历史上点过——持久化在 localStorage，刷新不复活）
const alreadyDone = computed(() => {
  return props.message.learnDone
    || chatStore.isTopicCompleted(guessedTopic.value)
    || chatStore.isTopicCompleted(chatStore.learningTopic)
    || chatStore.isTopicCompleted(headingGuess())
})

async function markLearned() {
  if (!chatStore.sessionId || completing.value || alreadyDone.value) return
  const topic = guessedTopic.value
  completing.value = true
  try {
    await completePathTopic(chatStore.sessionId, {
      topic,
      resource_id: props.message.resourceId || props.message.resource_id || '',
      time_spent_minutes: elapsedMinutes(5),
      self_evaluation: '聊天里点「我学完了」按钮标记完成',
    })
    props.message.learnDone = true
    // 把所有可能的主题叫法都存进"已完成"集合（标题叫法/正在学主题），
    // 这样刷新或重新进入对话后按钮依然是已按状态
    ;[topic, chatStore.learningTopic, headingGuess()].forEach(t => chatStore.markTopicCompleted(t))
    chatStore.addMessage({
      role: 'ai',
      content: `✅ 已把「${topic}」记入学习进度！去「学习路径」页看看解锁了什么新内容吧。`,
    })
  } catch (err) {
    chatStore.addMessage({
      role: 'ai',
      content: `❌ 记录进度失败：${err.message || err}。你也可以直接发"我想学习：主题名"，学完后说"完成了"来记进度。`,
    })
  }
  completing.value = false
}

const isUser = computed(() => props.message.role === 'user')
const isStreaming = computed(() => props.message.isStreaming)

// 检测内容是否包含 mermaid 思维导图
const isMermaid = computed(() => {
  if (props.message.resourceType === 'mindmap') return true
  const content = props.message.content || ''
  return content.includes('```mermaid') || content.startsWith('mindmap')
})

// 检测内容是否包含 notebook JSON 结构
const isNotebook = computed(() => {
  if (props.message.resourceType === 'notebook') return true
  const content = props.message.content || ''
  return content.includes('"cells"') && content.includes('"cell_type"')
})

// 检测是否为 quiz 练习题
const isQuiz = computed(() => {
  if (props.message.resourceType === 'quiz') return true
  const content = props.message.content || ''
  return content.includes('"questions"') && (content.includes('"stem"') || content.includes('"options"'))
})

// 解析 quiz JSON 数据供 QuizCard 使用
const quizData = computed(() => {
  if (!isQuiz.value) return null
  const content = props.message.content || ''
  try {
    // 去掉可能的 markdown 代码块包裹
    const cleaned = content.replace(/```(?:json)?\s*\n?/g, '').replace(/```\s*$/g, '')
    const parsed = JSON.parse(cleaned)
    if (parsed.questions?.length) return parsed
  } catch {
    // 尝试从内容中提取 JSON 对象
    const match = content.match(/\{[\s\S]*"questions"[\s\S]*\}/)
    if (match) {
      try { return JSON.parse(match[0]) } catch {}
    }
  }
  return null
})
</script>

<template>
  <div class="message-bubble" :class="{ user: isUser, ai: !isUser }">
    <div class="bubble-avatar">
      {{ isUser ? '👤' : '🤖' }}
    </div>
    <div class="bubble-content">
      <div class="bubble-header">
        <span class="bubble-role">{{ isUser ? '你' : '学习助手' }}</span>
      </div>
      <div class="bubble-body">
        <!-- 检测到 思维导图 Mermaid → 用 MermaidViewer 渲染 -->
        <MermaidViewer
          v-if="isMermaid && message.content"
          :code="message.content"
          :is-streaming="isStreaming"
        />
        <!-- 检测到 Notebook JSON → 用 NotebookViewer 渲染 -->
        <NotebookViewer
          v-else-if="isNotebook && message.content"
          :content="message.content"
          :is-streaming="isStreaming"
        />
        <!-- 检测到 Quiz JSON → 用 QuizCard 渲染 -->
        <QuizCard
          v-else-if="isQuiz && quizData"
          :data="quizData"
          @quiz-submitted="handleQuizSubmitted"
        />
        <!-- 普通 Markdown / 纯文本 -->
        <MarkdownCard
          v-else-if="message.content"
          :content="message.content"
          :is-streaming="isStreaming"
        />
        <span v-if="isStreaming && !message.content" class="streaming-cursor">▊</span>
      </div>
      <!-- 学习资源下方：一键"我学完了"按钮 -->
      <div v-if="isResourceMsg" class="learn-done-bar">
        <button
          v-if="!alreadyDone"
          class="learn-done-btn"
          :disabled="completing"
          @click="markLearned"
        >
          {{ completing ? '⏳ 正在记录…' : '✅ 我学完了，记入学习进度' }}
        </button>
        <span v-else class="learn-done-tip">✅ 已记入学习进度（再通过「练练手」即完成该主题）</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 12px;
}

.message-bubble.user {
  background: transparent;
  flex-direction: row-reverse;
}

.message-bubble.ai {
  background: var(--bg-primary);
}

.bubble-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  background: var(--bg-hover);
}

.bubble-content {
  flex: 1;
  min-width: 0;
}

.bubble-header {
  margin-bottom: 4px;
}

.bubble-role {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
}

.bubble-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
}

.streaming-cursor {
  display: inline-block;
  animation: blink 0.7s infinite;
  color: var(--accent-color);
}

.learn-done-bar {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-color);
}

.learn-done-btn {
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  background: var(--accent-color);
  color: white;
  transition: background 0.15s, transform 0.1s;
}

.learn-done-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.learn-done-btn:active:not(:disabled) {
  transform: scale(0.97);
}

.learn-done-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.learn-done-tip {
  font-size: 13px;
  font-weight: 600;
  color: #16a34a;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
