<script setup>
import { useRouter } from 'vue-router'
import { useChatStore } from '../../stores/chat'

defineProps({
  sidebarCollapsed: Boolean,
})

defineEmits(['toggle-sidebar'])

const router = useRouter()
const chatStore = useChatStore()

function handleLogout() {
  chatStore.logout()
  router.push('/auth')
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-left">
      <button class="toggle-btn" @click="$emit('toggle-sidebar')">
        ☰
      </button>
      <h1 class="app-title">🎓 个性化学习智能体</h1>
      <span class="course-badge">Python 程序设计</span>
    </div>
    <div class="topbar-right">
      <span v-if="chatStore.sessionId" class="session-indicator">
        🟢 学习中
      </span>
      <span class="user-name" v-if="chatStore.displayName">{{ chatStore.displayName }}</span>
      <button class="logout-btn" @click="handleLogout" title="退出登录">
        🚪 退出
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 20px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toggle-btn {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  color: var(--text-secondary);
}

.toggle-btn:hover {
  background: var(--bg-hover);
}

.app-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.course-badge {
  font-size: 12px;
  padding: 2px 10px;
  background: var(--accent-light);
  color: var(--accent-color);
  border-radius: 12px;
  font-weight: 500;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.session-indicator {
  font-size: 13px;
  color: var(--success-color);
}

.user-name {
  font-size: 13px;
  color: var(--text-secondary);
}

.logout-btn {
  background: none;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background 0.15s, color 0.15s;
}

.logout-btn:hover {
  background: #fee2e2;
  color: #dc2626;
  border-color: #fca5a5;
}
</style>
