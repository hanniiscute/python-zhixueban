import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn, clearAuth } from '../utils/auth'

const routes = [
  {
    path: '/auth',
    name: 'auth',
    component: () => import('../views/AuthView.vue'),
    meta: { title: '登录', guest: true },
  },
  {
    path: '/',
    name: 'home',
    component: () => import('../views/HomeView.vue'),
    meta: { title: '对话学习', icon: '💬', requiresAuth: true },
  },
  {
    path: '/onboarding',
    name: 'onboarding',
    component: () => import('../views/OnboardingView.vue'),
    meta: { title: '初始化画像', requiresAuth: true },
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('../views/ProfileView.vue'),
    meta: { title: '我的画像', icon: '👤', requiresAuth: true },
  },
  {
    path: '/resources',
    name: 'resources',
    component: () => import('../views/ResourcesView.vue'),
    meta: { title: '学习资源', icon: '📚', requiresAuth: true },
  },
  {
    path: '/learning-path',
    name: 'learning-path',
    component: () => import('../views/LearningPathView.vue'),
    meta: { title: '学习路径', icon: '🗺️', requiresAuth: true },
  },
  {
    path: '/evaluation',
    name: 'evaluation',
    component: () => import('../views/EvaluationView.vue'),
    meta: { title: '学习评估', icon: '📊', requiresAuth: true },
  },
  {
    path: '/report',
    name: 'report',
    component: () => import('../views/ReportView.vue'),
    meta: { title: '学习报告', icon: '📈', requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 登录守卫：未登录 / token 已过期 → 自动跳 /auth
// 这里除了看有没有 userId，还会检查 token 的过期时间。
// 少了过期判断的话，7 天到期后页面能进去但所有接口 401，表现为一直报错或白屏。
router.beforeEach((to) => {
  const requiresAuth = to.meta.requiresAuth
  const isGuest = to.meta.guest
  const valid = isLoggedIn()

  if (requiresAuth && !valid) {
    // 曾经登录过但现在失效 = 真的过期了，带上提示；从没登录过则安静跳过去
    const hadSession = !!localStorage.getItem('userId')
    if (hadSession) clearAuth()
    return hadSession ? { name: 'auth', query: { expired: '1' } } : { name: 'auth' }
  }
  if (isGuest && valid) {
    return { name: 'home' }
  }
})

export default router
