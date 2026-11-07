<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useChatStore } from '../../stores/chat'
import { useSSE } from '../../composables/useSSE'
import { useProfileStore } from '../../stores/profile'

const chatStore = useChatStore()
const profileStore = useProfileStore()
const { isStreaming, thinkingText, streamContent, currentResourceType, profileUpdates, send } = useSSE()

const inputText = ref('')

// 快捷指令：一键填入常用提问（不自动发送，用户可改完再发）
const quickCommands = [
  { icon: '🎯', text: '帮我规划一条学习路径' },
  { icon: '📝', text: '给我出 5 道练习题' },
  { icon: '📖', text: '用生活例子讲讲列表和元组的区别' },
  { icon: '🔍', text: '帮我分析一下我的学习基础' },
  { icon: '🧠', text: '最近学的知识点帮我做个小测验' },
]

function applyQuick(cmd) {
  if (isStreaming.value) return
  inputText.value = cmd
}

watch(streamContent, (val) => {
  if (chatStore.messages.length > 0) {
    const last = chatStore.messages[chatStore.messages.length - 1]
    if (last.isStreaming) {
      last.content = val
    }
  }
})

// 当 resource_start 事件确定资源类型后，标记到当前消息上
watch(currentResourceType, (type) => {
  if (chatStore.messages.length > 0) {
    const last = chatStore.messages[chatStore.messages.length - 1]
    if (last.isStreaming && type) {
      last.resourceType = type
    }
  }
})

// 会话 + 历史是否就绪。
// 以前这里是「固定 setTimeout 300ms 后无条件发送」，但 HomeView 挂载后会异步拉历史，
// 历史请求只要比 300ms 慢一拍，它返回时就会整体覆盖 messages，
// 把刚插入的「用户提问 + 空 AI 气泡」一起抹掉 —— 表现就是"点开始学习没反应"。
// 现在改成等真正就绪再发；期间轮询，超时兜底。
let alive = true
function waitForReady(timeout = 10000) {
  return new Promise((resolve) => {
    const startedAt = Date.now()
    const timer = setInterval(() => {
      const ready = Boolean(chatStore.sessionId) && chatStore.historyReady && !chatStore.isStreaming
      if (!alive || ready || Date.now() - startedAt > timeout) {
        clearInterval(timer)
        resolve(alive && Boolean(chatStore.sessionId))
      }
    }, 60)
  })
}

// 从学习路径跳转过来时，自动发送学习请求
onMounted(async () => {
  const topic = chatStore.pendingTopic
  const pending = chatStore.pendingMessage
  if (!topic && !pending) return
  // 先取走，避免重复触发；下面无论成功失败都会给用户一个可见结果
  chatStore.pendingTopic = ''
  chatStore.pendingMessage = ''

  const ok = await waitForReady()
  if (!alive) return
  if (!ok) {
    // 会话迟迟没就绪也不能让用户白点一次：把提问补回界面并说明原因
    chatStore.addMessage({ role: 'user', content: topic ? `我想学习：${topic}` : pending })
    chatStore.addMessage({
      role: 'ai',
      content: '⚠️ 会话还没准备好，这条消息没能发出去。请稍等两秒再点一次按钮～',
    })
    return
  }

  if (topic) {
    sendTopicMessage(topic)
  } else {
    inputText.value = pending
    handleSend()
  }
})

onBeforeUnmount(() => {
  alive = false
})

function sendTopicMessage(topic) {
  const text = `我想学习：${topic}`
  chatStore.setLearningTopic(topic)  // 记住正在学的主题，之后说"完成了"可记进度
  chatStore.addMessage({ role: 'user', content: text })

  const aiId = chatStore.nextMessageId()
  chatStore.addMessage({ id: aiId, role: 'ai', content: '', isStreaming: true })

  // 按 id 定位而不是盲取"最后一条"：万一这条被别处（历史覆盖等）换掉，
  // 直接放弃写入，总好过把整篇讲义错写到别的消息上
  const target = () => chatStore.messages.find(m => m.id === aiId)

  send(chatStore.sessionId, text, {
    onDone(data) {
      const msg = target()
      if (!msg) return
      msg.content = streamContent.value
      msg.isStreaming = false
      msg.metadata = data

      profileUpdates.value.forEach(({ dimension_updated, field, value }) => {
        profileStore.applySSEUpdate(dimension_updated, field, value)
      })
    },
    onError(err) {
      const msg = target()
      if (!msg) return
      msg.content = `❌ 出错了: ${err}`
      msg.isStreaming = false
    },
  })
}

function handleSend() {
  const text = inputText.value.trim()
  if (!text || isStreaming.value) return
  if (!chatStore.sessionId) return

  // 主动说"我想学习X" → 也记住主题（和点"开始学习"等效）
  const learnMatch = text.match(/我想学习[:：]?\s*(.+)/)
  if (learnMatch) {
    chatStore.setLearningTopic(learnMatch[1].trim())
  }

  // 说"完成了/学完了/学习完了"等 → 后端会自动把最近在学的主题记入学习进度
  // （检测在后端 orchestrator 做的前端兜底提示，这里只负责展示结果）
  const isCompletion = /((学|看|听|做)(习)?(完|好)|完成|搞定|掌握|学会)/.test(text)

  chatStore.addMessage({ role: 'user', content: text })
  inputText.value = ''

  const aiId = chatStore.nextMessageId()
  chatStore.addMessage({ id: aiId, role: 'ai', content: '', isStreaming: true })
  const target = () => chatStore.messages.find(m => m.id === aiId)

  send(chatStore.sessionId, text, {
    onDone(data) {
      const msg = target()
      if (!msg) return
      msg.content = streamContent.value
      msg.isStreaming = false
      msg.metadata = data

      profileUpdates.value.forEach(({ dimension_updated, field, value }) => {
        profileStore.applySSEUpdate(dimension_updated, field, value)
      })

      // 后端在 done 事件里带回是否记入进度
      if (data && data.path_completed) {
        chatStore.addMessage({
          role: 'ai',
          content: `✅ 已把「${data.path_completed}」记为开始学习！完成规则：开始学习 + 练练手通过（≥60%）才算完成这个主题——去「学习路径」页点「练练手」试试吧。`,
        })
      } else if (isCompletion) {
        chatStore.addMessage({
          role: 'ai',
          content: '💡 这次没能自动记进度——我不确定你在学哪个主题。去「学习路径」页点当前主题的「开始学习」（或在这里发「我想学习：主题名」），学完后再说一次「完成了」就能记上。',
        })
      }
    },
    onError(err) {
      const msg = target()
      if (!msg) return
      msg.content = `❌ 出错了: ${err}`
      msg.isStreaming = false
    },
  })
}
</script>

<template>
  <div class="chat-input-area">
    <!-- 快捷指令：一键填入，改完再发 -->
    <div v-if="!isStreaming" class="quick-commands">
      <button
        v-for="c in quickCommands"
        :key="c.text"
        class="quick-chip"
        :title="c.text"
        @click="applyQuick(c.text)"
      >{{ c.icon }} {{ c.text }}</button>
    </div>
    <div class="input-wrapper">
      <textarea
        v-model="inputText"
        class="chat-textarea"
        placeholder="输入学习需求，比如: 我想学for循环 / 给我出几道题 / 帮我分析基础..."
        rows="1"
        :disabled="isStreaming"
        @keydown.enter.exact.prevent="handleSend"
      ></textarea>
      <button
        class="send-btn"
        :disabled="!inputText.trim() || isStreaming"
        @click="handleSend"
      >
        {{ isStreaming ? '...' : '➤' }}
      </button>
    </div>
    <div class="input-hint">
      按 Enter 发送 · 支持自然语言
    </div>
  </div>
</template>

<style scoped>
.chat-input-area {
  max-width: 800px;
  margin: 0 auto;
}

/* 快捷指令条 */
.quick-commands {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.quick-chip {
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.quick-chip:hover {
  border-color: var(--accent-color);
  color: var(--accent-color);
  background: var(--accent-light);
}

.input-wrapper {
  display: flex;
  gap: 8px;
  align-items: center;  /* 垂直居中：单行输入不再贴底，上面不留空白 */
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
  transition: border-color 0.15s;
}

.input-wrapper:focus-within {
  border-color: var(--accent-color);
  box-shadow: 0 0 0 3px var(--accent-light);
}

.chat-textarea {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  font-size: 14px;
  line-height: 1.5;
  max-height: 120px;
  background: transparent;
  color: var(--text-primary);
  font-family: inherit;
}

.chat-textarea::placeholder {
  color: var(--text-placeholder);
}

.send-btn {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: var(--accent-color);
  color: white;
  font-size: 16px;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s;
}

.send-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.send-btn:disabled {
  background: var(--disabled-color);
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
}
</style>
