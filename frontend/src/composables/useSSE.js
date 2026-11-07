import { ref } from 'vue'
import { streamChat } from '../api'
import { useProfileStore } from '../stores/profile'
import { useChatStore } from '../stores/chat'

/**
 * SSE 流式对话 Composable
 */
export function useSSE() {
  const isStreaming = ref(false)
  const thinkingText = ref('')
  const streamContent = ref('')
  const currentResourceId = ref('')
  const currentResourceType = ref('')
  const profileUpdates = ref([])
  const profileStore = useProfileStore()
  const chatStore = useChatStore()

  // 流式状态必须同步进 store：ChatContainer 的平滑跟随滚动和"思考中"提示条
  // 读的是 chatStore.isStreaming / chatStore.thinkingText。之前这里只用局部 ref，
  // 从没写回 store，那两个功能一直是空转的（跟随不动、提示条从不显示）。
  function syncStreaming(val) {
    isStreaming.value = val
    chatStore.setStreaming(val)
    if (!val) chatStore.thinkingText = ''
  }

  function syncThinking(text) {
    thinkingText.value = text || ''
    chatStore.thinkingText = thinkingText.value
  }

  /**
   * 发送消息并处理 SSE 流
   */
  function send(sessionId, message, { onDone, onError } = {}) {
    syncStreaming(true)
    syncThinking('')
    streamContent.value = ''
    profileUpdates.value = []

    streamChat(sessionId, message, {
      onThinking(data) {
        syncThinking(data.status)
      },
      onProfile(data) {
        profileUpdates.value.push(data)
        // 实时应用画像更新到 store，对话过程中侧边栏即可看到变化
        if (data.dimension_updated && data.field && data.value !== undefined) {
          profileStore.applySSEUpdate(data.dimension_updated, data.field, data.value)
        }
      },
      onContent(data) {
        if (data.chunk) {
          streamContent.value += data.chunk
        }
      },
      onResourceStart(data) {
        currentResourceId.value = data.resource_id
        currentResourceType.value = data.type
        streamContent.value = ''
      },
      onResourceDone(data) {
        currentResourceId.value = ''
        currentResourceType.value = ''
        syncStreaming(false)
        onDone?.(data)
      },
      onPathUpdate(data) {
        onDone?.(data)
      },
      onDone(data) {
        syncThinking('')
        syncStreaming(false)
        onDone?.(data)
      },
      onError(err) {
        syncStreaming(false)
        syncThinking('')
        onError?.(err)
      },
    })
  }

  return {
    isStreaming,
    thinkingText,
    streamContent,
    currentResourceId,
    currentResourceType,
    profileUpdates,
    send,
  }
}
