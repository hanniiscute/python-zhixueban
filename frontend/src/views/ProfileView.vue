<script setup>
import { onMounted, ref } from 'vue'
import { useChatStore } from '../stores/chat'
import { useProfileStore } from '../stores/profile'
import { getProfile } from '../api'
import ProfilePanel from '../components/profile/ProfilePanel.vue'

const chatStore = useChatStore()
const profileStore = useProfileStore()
const loading = ref(true)

onMounted(async () => {
  if (chatStore.sessionId) {
    try {
      const data = await getProfile(chatStore.sessionId)
      profileStore.updateProfile(data)
    } catch (err) {
      console.error(err)
    }
  }
  loading.value = false
})
</script>

<template>
  <div class="profile-view">
    <div class="page-header">
      <h2>👤 我的学习画像</h2>
      <p class="page-desc">系统通过对话自动构建你的学习画像，越用越精准</p>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <ProfilePanel v-else />
  </div>
</template>

<style scoped>
.profile-view {
  max-width: 700px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  font-size: 20px;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.page-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.loading {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
}
</style>
