import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useProfileStore = defineStore('profile', () => {
  const profile = ref({
    knowledge_base: { level: '未知', known_concepts: [], unknown_concepts: [], score_map: {} },
    learning_style: { type: '未知', preferred_formats: [], avg_reading_time_ratio: 0.5 },
    error_patterns: { common_mistakes: [], error_prone_topics: [] },
    cognitive_level: { remember: 0, understand: 0, apply: 0, analyze: 0, evaluate: 0, create: 0 },
    interest_tendency: { directions: [], engagement_topics: [], skip_topics: [] },
    learning_pace: { avg_session_minutes: 0, completion_speed: '未知', peak_hours: [], streak_days: 0 },
    learning_goal: { primary: '', secondary: '', timeline: '', target_projects: [] },
  })

  const lastUpdated = ref('')
  const confidence = ref(0)

  function updateProfile(data) {
    if (data.profile) {
      profile.value = data.profile
    }
    if (data.last_updated) lastUpdated.value = data.last_updated
    if (data.confidence) confidence.value = data.confidence
  }

  // 把后端推来的值还原成可入列的数组元素。
  // 列表型画像字段在数据库里单行存 JSON 数组，所以 SSE 推来的既可能是
  // 一个数组本身，也可能是 '["Java"]' 这种 JSON 字符串。
  // 直接 push 原值会让页面显示成 ['["Java"]'] 这种嵌套格式。
  function _expandValue(value) {
    if (Array.isArray(value)) return value.filter((v) => v !== null && v !== undefined && v !== '')
    if (typeof value === 'string') {
      const t = value.trim()
      if (t.startsWith('[')) {
        try {
          const parsed = JSON.parse(t)
          if (Array.isArray(parsed)) return parsed
        } catch {
          // 不是合法 JSON，按普通字符串处理
        }
      }
      return t ? [t] : []
    }
    return value === null || value === undefined ? [] : [value]
  }

  function applySSEUpdate(dimension, field, value) {
    const dimMap = {
      knowledge_base: 'knowledge_base',
      learning_style: 'learning_style',
      error_patterns: 'error_patterns',
      cognitive_level: 'cognitive_level',
      interest_tendency: 'interest_tendency',
      learning_pace: 'learning_pace',
      learning_goal: 'learning_goal',
    }
    const key = dimMap[dimension]
    if (key && profile.value[key]) {
      if (Array.isArray(profile.value[key][field])) {
        const existing = profile.value[key][field]
        for (const item of _expandValue(value)) {
          // 统一转字符串比对，避免 1 和 '1' 都被当成不同元素重复入列
          const s = String(item)
          if (!existing.some((e) => String(e) === s)) {
            existing.push(s)
          }
        }
      } else {
        profile.value[key][field] = value
      }
    }
  }

  return {
    profile,
    lastUpdated,
    confidence,
    updateProfile,
    applySSEUpdate,
  }
})
