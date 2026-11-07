<script setup>
import { useRoute, useRouter } from 'vue-router'

defineProps({
  collapsed: Boolean,
})

const route = useRoute()
const router = useRouter()

const navItems = [
  { path: '/', name: 'home', label: '对话学习', icon: '💬' },
  { path: '/profile', name: 'profile', label: '我的画像', icon: '👤' },
  { path: '/resources', name: 'resources', label: '学习资料库', icon: '📚' },
  { path: '/learning-path', name: 'learning-path', label: '学习路径', icon: '🗺️' },
  { path: '/evaluation', name: 'evaluation', label: '学习评估', icon: '📊' },
  { path: '/report', name: 'report', label: '学习报告', icon: '📈' },
]

function navigate(path) {
  router.push(path)
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed }">
    <nav class="sidebar-nav">
      <div
        v-for="item in navItems"
        :key="item.name"
        class="nav-item"
        :class="{ active: route.name === item.name }"
        @click="navigate(item.path)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span v-show="!collapsed" class="nav-label">{{ item.label }}</span>
      </div>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 220px;
  min-width: 220px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-color);
  padding: 16px 12px;
  transition: width 0.2s, min-width 0.2s;
  overflow: hidden;
}

.sidebar.collapsed {
  width: 56px;
  min-width: 56px;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
  color: var(--text-secondary);
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--accent-light);
  color: var(--accent-color);
  font-weight: 600;
}

.nav-icon {
  font-size: 18px;
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

.nav-label {
  font-size: 14px;
}

@media (max-width: 768px) {
  .sidebar {
    width: 56px;
    min-width: 56px;
  }
  .nav-label {
    display: none;
  }
}
</style>
