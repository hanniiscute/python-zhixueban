import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const sessionId = ref(localStorage.getItem('sessionId') || '')
  const userId = ref(localStorage.getItem('userId') || '')
  const displayName = ref(localStorage.getItem('displayName') || '')
  const userName = ref('')
  const messages = ref([])
  const isStreaming = ref(false)
  const thinkingText = ref('')
  const pendingTopic = ref('')  // 从学习路径跳转时携带的主题
  const pendingMessage = ref('')  // 其他页面带来的整句待发送消息（如"帮我规划学习路径"）
  // 会话/历史是否已就绪。HomeView 挂载后会异步拉历史，ChatInput 必须等它完成才能
  // 自动发送 pendingTopic/pendingMessage —— 否则刚插进 messages 的提问会被随后
  // 返回的历史整体覆盖掉，用户只看到"点了没反应"。
  const historyReady = ref(false)
  function setHistoryReady(val) {
    historyReady.value = !!val
  }
  // 当前正在学习的主题（记入学习进度用）：点"开始学习"或说"我想学习X"时设置，
  // 聊天里说"完成了"时用它定位要标记完成的主题。持久化到 localStorage，刷新不丢。
  const learningTopic = ref(localStorage.getItem('learningTopic') || '')
  // 已标记过"学完了"的主题集合（持久化）：让"我学完了"按钮按过一次就永久变灰，刷新/切页不复活
  // JSON.parse 必须兜底 —— 本地数据一旦损坏（被手工改过/写入中断），
  // 这里抛异常会让整个 store 初始化失败，表现为打开就白屏。
  function _loadCompletedTopics() {
    try {
      const parsed = JSON.parse(localStorage.getItem('learnDoneTopics') || '[]')
      return Array.isArray(parsed) ? parsed : []
    } catch {
      localStorage.removeItem('learnDoneTopics')
      return []
    }
  }
  const completedTopics = ref(_loadCompletedTopics())

  function markTopicCompleted(topic) {
    if (!topic || completedTopics.value.includes(topic)) return
    completedTopics.value.push(topic)
    localStorage.setItem('learnDoneTopics', JSON.stringify(completedTopics.value))
  }

  function isTopicCompleted(topic) {
    return !!topic && completedTopics.value.includes(topic)
  }

  function setLearningTopic(topic) {
    learningTopic.value = topic || ''
    if (topic) {
      localStorage.setItem('learningTopic', topic)
    } else {
      localStorage.removeItem('learningTopic')
    }
  }

  function setSession(id, name) {
    sessionId.value = id
    localStorage.setItem('sessionId', id)
    if (name) userName.value = name
  }

  function setUser(id, name) {
    userId.value = id
    displayName.value = name || ''
    localStorage.setItem('userId', id)
    localStorage.setItem('displayName', name || '')
  }

  function setToken(token) {
    localStorage.setItem('token', token || '')
  }

  function getToken() {
    return localStorage.getItem('token') || ''
  }

  function logout() {
    userId.value = ''
    displayName.value = ''
    sessionId.value = ''
    messages.value = []
    learningTopic.value = ''
    localStorage.removeItem('userId')
    localStorage.removeItem('displayName')
    localStorage.removeItem('sessionId')
    localStorage.removeItem('token')
    localStorage.removeItem('learningTopic')
    completedTopics.value = []
    localStorage.removeItem('learnDoneTopics')
  }

  // 消息 id 必须唯一：之前用 Date.now()（毫秒级），而发一条消息会连续
  // addMessage 两次（用户提问 + AI 空回复），中间没有任何耗时操作，
  // 两条消息几乎必然落在同一毫秒拿到相同 id。ChatContainer 用 :key="msg.id"
  // 渲染，key 撞车后 Vue 每次更新都分不清这两个节点，只能反复卸载重建 ——
  // 流式期间每来一个 chunk 就重建一次，表现就是画面不停弹跳。
  // 这里改成「时间戳 + 自增序号」，同毫秒也绝不会重复。
  let msgSeq = 0
  function nextMessageId() {
    msgSeq += 1
    return `msg-${Date.now()}-${msgSeq}`
  }

  function addMessage(msg) {
    messages.value.push({
      ...msg,
      id: msg?.id ?? nextMessageId(),
    })
  }

  function updateLastMessage(chunk) {
    if (messages.value.length > 0) {
      messages.value[messages.value.length - 1].content += chunk
    }
  }

  function setStreaming(val) {
    isStreaming.value = val
  }

  function clearMessages() {
    messages.value = []
  }

  return {
    sessionId,
    userId,
    displayName,
    userName,
    messages,
    isStreaming,
    thinkingText,
    pendingTopic,
    pendingMessage,
    historyReady,
    setHistoryReady,
    learningTopic,
    setLearningTopic,
    completedTopics,
    markTopicCompleted,
    isTopicCompleted,
    setSession,
    setUser,
    setToken,
    getToken,
    logout,
    addMessage,
    nextMessageId,
    updateLastMessage,
    setStreaming,
    clearMessages,
  }
})
