<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import TopBar from './TopBar.vue'
import ChatInput from '../chat/ChatInput.vue'

const route = useRoute()
const sidebarCollapsed = ref(false)

import { computed } from 'vue'

const isFullScreen = computed(() => route.name === 'auth' || route.name === 'onboarding')
const showChatInput = computed(() => route.name === 'home')
</script>

<template>
  <!-- 登录/问卷页：无壳渲染 -->
  <div v-if="isFullScreen" class="fullscreen-only">
    <router-view />
  </div>

  <!-- 其他页面：完整布局 -->
  <div v-else class="app-shell">
    <TopBar :sidebar-collapsed="sidebarCollapsed" @toggle-sidebar="sidebarCollapsed = !sidebarCollapsed" />
    <div class="app-body">
      <Sidebar :collapsed="sidebarCollapsed" />
      <main class="main-content" :class="{ 'no-scroll': route.name === 'home' }">
        <router-view />
      </main>
    </div>
    <div v-if="showChatInput" class="bottom-bar">
      <ChatInput />
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
}

.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  background: var(--bg-main);
}

/* 对话页：聊天区自己有滚动条（height:100% + overflow-y:auto）。
   外层再叠一层滚动容器，padding 撑出的高度会让外层也能滚，
   滚到底时内层停了、外层还能再滚一段，整个聊天区会额外跳一下。
   所以首页让外层不滚动，内边距交给 ChatContainer 自己。 */
.main-content.no-scroll {
  overflow: hidden;
  padding: 0;
}

.bottom-bar {
  border-top: 1px solid var(--border-color);
  padding: 16px 24px;
  background: var(--bg-primary);
}

/* 响应式 */
@media (max-width: 768px) {
  .main-content {
    padding: 12px;
  }
  .bottom-bar {
    padding: 8px 12px;
  }
}
</style>
