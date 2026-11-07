<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useChatStore } from '../../stores/chat'
import MessageBubble from './MessageBubble.vue'

const chatStore = useChatStore()
const containerRef = ref(null)

// ===== 自动跟随滚动（豆包式） =====
// 流式生成时平滑地慢慢往下跟；用户往上翻就停下，并显示"回到底部"按钮
const autoFollow = ref(true)
const showBackBtn = ref(false)
let rafId = null

// 我们自己触发的滚动（跟随）也会派发 scroll 事件。如果不加区分，
// 内容一次增长较多时会被误判成"用户上翻"，跟随就自己停掉了。
// 这里用一个短时窗把程序滚动标记出来，onScroll 期间忽略。
let programmaticUntil = 0
function markProgrammatic() {
  programmaticUntil = performance.now() + 150
}

function nearBottom() {
  const el = containerRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

// 用户滚动时判断意图：贴着底部 = 想跟随；离开底部 = 想自己看
function onScroll() {
  if (performance.now() < programmaticUntil) return
  const near = nearBottom()
  autoFollow.value = near
  showBackBtn.value = !near && chatStore.messages.length > 0
}

// 滚轮往上 → 明确是想往回看，立刻停止跟随
function onWheel(e) {
  if (e.deltaY < 0) {
    autoFollow.value = false
    showBackBtn.value = true
  }
}

function backToBottom() {
  const el = containerRef.value
  if (!el) return
  markProgrammatic()
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  autoFollow.value = true
  showBackBtn.value = false
}

// 每帧渐进滚动：不瞬移，像豆包一样"慢慢滑"。
// 系数用 0.3 而不是 0.1 —— 太慢会在内容连续增长时越落越远，
// 看起来像在追赶、发飘；0.3 大约 5~6 帧就贴回底部。
// 注意：chatStore.isStreaming 之前一直是 false（useSSE 没把状态写回 store），
// 这个循环实际从未生效过，现在已接通。
function followLoop() {
  const el = containerRef.value
  if (el && autoFollow.value && chatStore.isStreaming) {
    const target = el.scrollHeight - el.clientHeight
    if (target - el.scrollTop > 1) {
      markProgrammatic()
      el.scrollTop += (target - el.scrollTop) * 0.3
    }
  }
  rafId = requestAnimationFrame(followLoop)
}

onMounted(() => {
  rafId = requestAnimationFrame(followLoop)
})
onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  if (secTimer) clearInterval(secTimer)
})

// 生成一份讲义要 40~60 秒，期间 AI 气泡是空的，只有一个闪烁光标 ——
// 用户看到的就是"点了没反应"。这里按时间推进一个「分步进度」，
// 把真实的工作流程可视化，观感从"卡住了"变成"它在一步步干活"。
const elapsedSec = ref(0)
let secTimer = null
watch(
  () => chatStore.isStreaming,
  (streaming) => {
    if (secTimer) { clearInterval(secTimer); secTimer = null }
    if (streaming) {
      elapsedSec.value = 0
      secTimer = setInterval(() => { elapsedSec.value += 1 }, 1000)
    }
  }
)

// 与后端真实流程对应的三个阶段（阈值按实测耗时设定）
const GEN_STEPS = [
  { label: '分析你的学习画像', until: 6 },
  { label: '检索课程知识库', until: 15 },
  { label: '生成专属学习内容', until: Infinity },
]
const genSteps = computed(() => {
  const t = elapsedSec.value
  let currentIdx = GEN_STEPS.findIndex(s => t < s.until)
  if (currentIdx === -1) currentIdx = GEN_STEPS.length - 1
  return GEN_STEPS.map((s, i) => ({
    label: s.label,
    state: i < currentIdx ? 'done' : i === currentIdx ? 'active' : 'pending',
  }))
})
const elapsedText = computed(() => {
  const t = elapsedSec.value
  return t >= 3 ? `已用时 ${t}s` + (t >= 30 ? '，内容较长请稍候' : '') : ''
})
watch(
  () => chatStore.messages.length,
  async () => {
    await nextTick()
    if (containerRef.value && autoFollow.value) {
      markProgrammatic()
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }
)

// 生成结束时，若在跟随则最后贴到底
watch(
  () => chatStore.isStreaming,
  async (streaming) => {
    if (!streaming && autoFollow.value) {
      await nextTick()
      if (containerRef.value) {
        markProgrammatic()
        containerRef.value.scrollTop = containerRef.value.scrollHeight
      }
      showBackBtn.value = false
    }
  }
)
</script>

<template>
  <div
    class="chat-container"
    ref="containerRef"
    @scroll="onScroll"
    @wheel="onWheel"
  >
    <div v-if="chatStore.messages.length === 0" class="welcome-state">
      <div class="welcome-icon">🎓</div>
      <h2>欢迎来到个性化学习智能体</h2>
      <p class="welcome-desc">
        我是你的 <strong>Python 程序设计</strong> 学习助手。<br />
        你可以直接告诉我你的需求，我会为你生成专属学习内容。
      </p>
      <div class="welcome-suggestions">
        <span class="suggestion-tag">我想了解一下Python基础</span>
        <span class="suggestion-tag">帮我分析一下我的编程基础</span>
        <span class="suggestion-tag">给我出几道循环的练习题</span>
        <span class="suggestion-tag">生成for循环的思维导图</span>
        <span class="suggestion-tag">我想做列表操作的代码实操</span>
      </div>
    </div>

    <div v-for="msg in chatStore.messages" :key="msg.id" class="message-wrapper">
      <MessageBubble :message="msg" />
    </div>

    <!-- 思考中指示器：分步进度（分析画像 → 检索知识库 → 生成内容） -->
    <div v-if="chatStore.isStreaming" class="thinking-bar">
      <div class="thinking-steps">
        <div
          v-for="(step, i) in genSteps"
          :key="i"
          class="thinking-step"
          :class="step.state"
        >
          <span class="step-icon">
            <template v-if="step.state === 'done'">✓</template>
            <template v-else-if="step.state === 'active'"><span class="step-spinner"></span></template>
            <template v-else>{{ i + 1 }}</template>
          </span>
          <span class="step-label">{{ step.label }}</span>
        </div>
      </div>
      <span v-if="elapsedText" class="thinking-elapsed">{{ elapsedText }}</span>
    </div>

    <!-- 回到底部悬浮按钮（用户上翻查看时出现） -->
    <button v-if="showBackBtn" class="back-bottom-btn" @click="backToBottom">
      ↓ 回到底部
    </button>
  </div>
</template>

<style scoped>
.chat-container {
  max-width: 800px;
  margin: 0 auto;
  height: 100%;
  overflow-y: auto;
  padding: 16px 24px;
  position: relative;
  scroll-behavior: auto;
  /* 消息内容在流式期间会不断变高，关掉浏览器滚动锚定可避免它反向修正
     scrollTop 造成的上下拉扯 */
  overflow-anchor: none;
}

.back-bottom-btn {
  position: sticky;
  bottom: 16px;
  margin-left: auto;
  margin-right: 24px;
  display: block;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
  background: var(--bg-primary);
  color: var(--text-secondary);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  z-index: 5;
  transition: color 0.15s, border-color 0.15s;
}

.back-bottom-btn:hover {
  color: var(--accent-color);
  border-color: var(--accent-color);
}

.welcome-state {
  text-align: center;
  padding: 60px 20px;
}

.welcome-icon {
  font-size: 56px;
  margin-bottom: 16px;
}

.welcome-state h2 {
  font-size: 22px;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.welcome-desc {
  font-size: 15px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin-bottom: 28px;
}

.welcome-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.suggestion-tag {
  display: inline-block;
  padding: 8px 16px;
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  background: var(--bg-primary);
}

.suggestion-tag:hover {
  border-color: var(--accent-color);
  color: var(--accent-color);
  background: var(--accent-light);
}

.message-wrapper {
  margin-bottom: 4px;
}

.thinking-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  color: var(--text-muted);
  font-size: 13px;
}

.thinking-steps {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.thinking-step {
  display: flex;
  align-items: center;
  gap: 8px;
  transition: color 0.3s;
}

.thinking-step.done { color: var(--text-muted); opacity: 0.75; }
.thinking-step.active { color: var(--accent-color); font-weight: 500; }
.thinking-step.pending { color: var(--text-muted); opacity: 0.45; }

.step-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 11px;
  flex-shrink: 0;
}

.step-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid var(--accent-light);
  border-top-color: var(--accent-color);
  border-radius: 50%;
  display: inline-block;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.thinking-elapsed {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 768px) {
  .chat-container { padding: 12px 12px; }
  .back-bottom-btn { margin-right: 12px; }
}
</style>
