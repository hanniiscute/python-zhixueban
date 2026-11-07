<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'
import { register, login, createSession, getProfile } from '../api'

const router = useRouter()
const route = useRoute()
const chatStore = useChatStore()
const profileStore = useProfileStore()

const mode = ref('login') // 'login' | 'register'
const form = ref({ username: '', password: '', display_name: '' })
const error = ref('')
const loading = ref(false)

onMounted(() => {
  if (chatStore.userId) {
    router.replace('/')
    return
  }
  // 从 401 兜底跳转过来：提示登录已过期
  if (route.query.expired) {
    error.value = '登录已过期，请重新登录'
  }
})

async function submit() {
  error.value = ''

  if (!form.value.username || !form.value.password) {
    error.value = '请填写用户名和密码'
    return
  }
  if (mode.value === 'register' && form.value.password.length < 6) {
    error.value = '密码长度至少6位'
    return
  }

  loading.value = true
  try {
    let res
    if (mode.value === 'register') {
      res = await register({
        username: form.value.username,
        password: form.value.password,
        display_name: form.value.display_name,
      })
    } else {
      res = await login({
        username: form.value.username,
        password: form.value.password,
      })
    }

    chatStore.setUser(res.user_id, res.display_name || res.username)
    chatStore.setToken(res.token || '')

    // Create or resume session
    const sessionRes = await createSession({
      user_id: res.user_id,
      course: 'Python程序设计',
    })
    chatStore.setSession(sessionRes.session_id)
    chatStore.addMessage({ role: 'ai', content: sessionRes.greeting })

    // Load profile
    try {
      const profileData = await getProfile(sessionRes.session_id)
      profileStore.updateProfile(profileData)
    } catch {}

    // 注册后先进问卷，登录直接进主页
    router.replace(mode.value === 'register' ? '/onboarding' : '/')
  } catch (err) {
    error.value = err.message || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <!-- 左侧品牌区 -->
    <div class="auth-left">
      <div class="brand-content">
        <h1>🎓 个性化学习智能体</h1>
        <p>AI驱动的自适应学习系统</p>
        <div class="feature-list">
          <div class="feature-item">
            <span class="feature-icon">🧠</span>
            <span>7维学习画像，精准定位你的学习特征</span>
          </div>
          <div class="feature-item">
            <span class="feature-icon">📚</span>
            <span>AI生成个性化课程、练习、导图</span>
          </div>
          <div class="feature-item">
            <span class="feature-icon">🗺️</span>
            <span>动态学习路径，跟着知识图谱成长</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧登录区 -->
    <div class="auth-right">
      <div class="auth-card">
        <div class="card-header">
          <h2>{{ mode === 'login' ? '欢迎回来' : '创建账号' }}</h2>
          <p>{{ mode === 'login' ? '登录你的学习账号' : '开启你的个性化学习之旅' }}</p>
        </div>

        <form @submit.prevent="submit" class="auth-form">
          <div class="field">
            <label>用户名</label>
            <input
              v-model="form.username"
              type="text"
              placeholder="请输入用户名"
              autocomplete="username"
              :disabled="loading"
            />
          </div>

          <div class="field">
            <label>密码</label>
            <input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              autocomplete="current-password"
              :disabled="loading"
            />
          </div>

          <div v-if="mode === 'register'" class="field">
            <label>昵称 <span class="optional">(选填)</span></label>
            <input
              v-model="form.display_name"
              type="text"
              placeholder="你希望我们怎么称呼你？"
              :disabled="loading"
            />
          </div>

          <p v-if="error" class="error-msg">{{ error }}</p>

          <button type="submit" class="submit-btn" :disabled="loading">
            {{ loading ? '请稍候...' : (mode === 'login' ? '登  录' : '注  册') }}
          </button>
        </form>

        <div class="switch-mode">
          {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
          <button class="link-btn" @click="mode = mode === 'login' ? 'register' : 'login'; error = ''">
            {{ mode === 'login' ? '立即注册' : '去登录' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  display: flex;
  height: 100vh;
  background: var(--bg-primary);
}

/* ====== 左侧品牌区 ====== */
.auth-left {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 40%, #0f3460 100%);
  color: #fff;
  padding: 60px;
}

.brand-content h1 {
  font-size: 32px;
  margin: 0 0 8px;
}

.brand-content > p {
  font-size: 16px;
  opacity: 0.7;
  margin: 0 0 40px;
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
}

.feature-icon {
  font-size: 22px;
  flex-shrink: 0;
}

/* ====== 右侧登录区 ====== */
.auth-right {
  width: 460px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: var(--bg-primary);
}

.auth-card {
  width: 100%;
  max-width: 380px;
}

.card-header {
  margin-bottom: 32px;
}

.card-header h2 {
  font-size: 24px;
  color: var(--text-primary);
  margin: 0 0 6px;
}

.card-header p {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.optional {
  font-weight: 400;
  color: var(--text-muted);
}

.field input {
  padding: 10px 14px;
  border: 1.5px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
  background: var(--bg-primary);
  color: var(--text-primary);
}

.field input:focus {
  border-color: var(--accent-color);
}

.field input:disabled {
  opacity: 0.6;
}

.error-msg {
  color: #e74c3c;
  font-size: 13px;
  margin: 0;
}

.submit-btn {
  margin-top: 6px;
  padding: 12px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.submit-btn:hover {
  opacity: 0.9;
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.switch-mode {
  text-align: center;
  margin-top: 24px;
  font-size: 13px;
  color: var(--text-muted);
}

.link-btn {
  background: none;
  border: none;
  color: #667eea;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
}

.link-btn:hover {
  text-decoration: underline;
}

/* ====== 响应式 ====== */
@media (max-width: 768px) {
  .auth-left {
    display: none;
  }

  .auth-right {
    flex: 1;
    width: 100%;
  }
}
</style>
