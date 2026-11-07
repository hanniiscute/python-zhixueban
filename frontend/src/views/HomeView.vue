<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'
import { createSession, getProfile, getChatHistory } from '../api'
import ChatContainer from '../components/chat/ChatContainer.vue'

const router = useRouter()
const chatStore = useChatStore()
const profileStore = useProfileStore()

async function loadHistory() {
  if (!chatStore.sessionId) return
  try {
    const data = await getChatHistory(chatStore.sessionId)
    if (!data.messages?.length) return
    // 绝不能在流式进行中整体替换 messages：从学习路径点「开始学习」跳过来时，
    // ChatInput 会立刻插入「用户提问 + 空 AI 气泡」并开始推流，历史请求稍慢一步
    // 返回就会把这两条一起抹掉，用户看到的就是"点了没反应"。
    if (chatStore.messages.some(m => m.isStreaming)) {
      console.warn('[HomeView] 流式进行中，跳过历史覆盖')
      return
    }
    chatStore.messages = data.messages.map(m => ({
      id: chatStore.nextMessageId(),
      role: m.role,
      content: m.content,
      resourceType: null,
      isStreaming: false,
    }))
  } catch (err) {
    console.error('加载历史失败:', err)
  }
}

onMounted(async () => {
  // 挂载期间先置 false：ChatInput 必须等会话与历史都就绪再自动发消息
  chatStore.setHistoryReady(false)
  try {
    if (!chatStore.sessionId) {
      try {
        const res = await createSession({
          user_id: chatStore.userId,
          course: 'Python程序设计',
        })
        chatStore.setSession(res.session_id)
        chatStore.addMessage({ role: 'ai', content: res.greeting })
      } catch (err) {
        console.error('创建会话失败:', err)
        if (err.message?.includes('用户不存在')) {
          chatStore.logout()
        }
      }
    } else {
      // 已有 session，加载历史
      await loadHistory()
    }

    if (chatStore.sessionId) {
      try {
        const data = await getProfile(chatStore.sessionId)
        profileStore.updateProfile(data)

        // 如果画像为空且未填过问卷 → 跳转问卷
        const dims = countFilledDimensions(data?.profile)
        if (dims < 2 && !localStorage.getItem('onboarding_done')) {
          router.push('/onboarding')
        }
      } catch (err) {
        console.error('加载画像失败:', err)
      }
    }
  } finally {
    chatStore.setHistoryReady(true)
  }
})

function countFilledDimensions(profile) {
  if (!profile) return 0
  let count = 0
  const checks = [
    profile.knowledge_base?.level,
    profile.learning_style?.type,
    profile.learning_goal?.primary,
    profile.interest_tendency?.directions?.length > 0,
    profile.learning_pace?.daily_available_hours || profile.learning_pace?.completion_speed,
    profile.cognitive_level?.thinking_style,
  ]
  checks.forEach(c => { if (c) count++ })
  return count
}
</script>

<template>
  <div class="home-view">
    <ChatContainer />
  </div>
</template>

<style scoped>
.home-view {
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
