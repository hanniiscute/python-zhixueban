import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/styles/main.css'

// 全局 401 兜底：登录态缺失/过期时，自动清除旧登录信息并跳回登录页。
// 覆盖所有 API 调用（含 SSE 流式），无需在每个请求里单独处理。
const _rawFetch = window.fetch
window.fetch = async (...args) => {
  const res = await _rawFetch(...args)
  try {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || ''
    if (res.status === 401 && url.includes('/api/') && !url.includes('/api/auth/')) {
      localStorage.removeItem('token')
      localStorage.removeItem('userId')
      localStorage.removeItem('sessionId')
      localStorage.removeItem('displayName')
      if (!location.pathname.startsWith('/auth')) {
        location.href = '/auth?expired=1'  // 整页跳转，顺带重置所有内存状态
      }
    }
  } catch {}
  return res
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
