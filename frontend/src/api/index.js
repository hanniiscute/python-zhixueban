/** API 调用封装 */

const BASE_URL = '/api'

/** 统一请求头：自动附带登录 token */
function authHeaders(extra = {}) {
  const token = localStorage.getItem('token') || ''
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  }
}

// ============ 认证 ============

export async function register(data) {
  const res = await fetch(`${BASE_URL}/auth/register`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '注册失败')
  }
  return res.json()
}

export async function login(data) {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '登录失败')
  }
  return res.json()
}

// ============ 基础 ============

export async function createSession(data) {
  const res = await fetch(`${BASE_URL}/session`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '创建会话失败')
  }
  return res.json()
}

export async function getSession(sessionId) {
  const res = await fetch(`${BASE_URL}/session/${sessionId}`, { headers: authHeaders() })
  return res.json()
}

// 错题针对性讲解：提交答案后，把错题发给 AI 生成集中讲解
export async function explainMistakes(sessionId, topic, mistakes) {
  const res = await fetch(`${BASE_URL}/tutoring/explain-mistakes`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ session_id: sessionId, topic, mistakes }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '获取错题讲解失败')
  }
  return res.json()
}

// ============ 错题本 / 复习清单 ===========

// 拉取未掌握的错题（复习清单）
export async function getWrongQuestions(sessionId) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/wrong-questions`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('获取错题本失败')
  return res.json()
}

// 标记某道错题已掌握
export async function resolveWrongQuestion(sessionId, questionId) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/wrong-questions/${questionId}/resolve`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '操作失败')
  }
  return res.json()
}

// ============ AI 学习报告 ===========

// 生成（并缓存）学习报告
export async function generateReport(sessionId) {
  const res = await fetch(`${BASE_URL}/report/${sessionId}/generate`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '报告生成失败')
  }
  return res.json()
}

// 读取上次生成的报告
export async function getCachedReport(sessionId) {
  const res = await fetch(`${BASE_URL}/report/${sessionId}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('获取报告失败')
  return res.json()
}

// ============ 流式对话（核心） ============

export async function getChatHistory(sessionId) {
  const res = await fetch(`${BASE_URL}/chat/history/${sessionId}`, { headers: authHeaders() })
  if (!res.ok) return { messages: [], resources: [] }
  return res.json()
}

export function streamChat(sessionId, message, callbacks) {
  const { onThinking, onProfile, onContent, onResourceStart, onResourceDone, onPathUpdate, onDone, onError } = callbacks

  fetch(`${BASE_URL}/chat/stream`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      session_id: sessionId,
      message,
      context: {},
    }),
  }).then(async (response) => {
    if (!response.ok) {
      onError?.(`HTTP ${response.status}`)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    // ⚠️ currentEvent 必须在外层持有：SSE 的 `event:` 与 `data:` 两行有可能被
    // 网络分片切开，若在每个分片内部重置，跨分片的事件就会被丢掉（表现为"没回复"）。
    let currentEvent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))

            switch (currentEvent) {
              case 'thinking':
                onThinking?.(data)
                break
              case 'profile':
                onProfile?.(data)
                break
              case 'content':
                onContent?.(data)
                break
              case 'resource_start':
                onResourceStart?.(data)
                break
              case 'resource_done':
                onResourceDone?.(data)
                break
              case 'path_update':
                onPathUpdate?.(data)
                break
              case 'done':
                onDone?.(data)
                break
            }
          } catch {
            // skip parse errors
          }
        }
      }
    }
  }).catch(err => {
    onError?.(err.message)
  })
}

// ============ 画像 ============

export async function getProfile(sessionId) {
  const res = await fetch(`${BASE_URL}/profile/${sessionId}`, { headers: authHeaders() })
  return res.json()
}

export async function getProfileHistory(sessionId, dimension) {
  const res = await fetch(`${BASE_URL}/profile/${sessionId}/history?dimension=${dimension}`, { headers: authHeaders() })
  return res.json()
}

// 入门问卷
export async function saveQuestionnaire(data) {
  const res = await fetch(`${BASE_URL}/profile/questionnaire`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '提交失败')
  }
  return res.json()
}

// ============ 资源 ============

export async function getResources(sessionId, params = {}) {
  // 过滤掉 undefined/null/空字符串，避免发送 type=undefined
  const clean = {}
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') clean[k] = v
  }
  const query = new URLSearchParams(clean).toString()
  const res = await fetch(`${BASE_URL}/resources/${sessionId}${query ? '?' + query : ''}`, { headers: authHeaders() })
  return res.json()
}

export async function getResourceDetail(sessionId, resourceId) {
  const res = await fetch(`${BASE_URL}/resources/${sessionId}/${resourceId}`, { headers: authHeaders() })
  return res.json()
}

export async function submitFeedback(sessionId, resourceId, data) {
  const res = await fetch(`${BASE_URL}/resources/${sessionId}/${resourceId}/feedback`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  return res.json()
}

// ============ 学习路径 ============

export async function getLearningPath(sessionId) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}`, { headers: authHeaders() })
  return res.json()
}

export async function getRecommendations(sessionId, count = 5) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/recommendations?count=${count}`, { headers: authHeaders() })
  return res.json()
}

export async function completeTopic(sessionId, data) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/complete`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  return res.json()
}

// 标记主题「已开始学习」（完成规则：开始学习 + 练练手通过 才算完成）
export async function startTopic(sessionId, topic) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/start-topic`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ topic }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '标记开始学习失败')
  }
  return res.json()
}

// 练练手 — 闯关测验
export async function startPractice(sessionId, topic, force = false) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/practice/start`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ topic, force }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '题目生成失败')
  }
  return res.json()
}

export async function submitPractice(sessionId, data) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/practice/submit`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  return res.json()
}

// 标记主题学习完成（聊天里说"完成了"时调用）
export async function completePathTopic(sessionId, data) {
  const res = await fetch(`${BASE_URL}/learning-path/${sessionId}/complete`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '标记完成失败')
  }
  return res.json()
}

// ============ 评估 ============

export async function getEvaluation(sessionId, scope = 'overall') {
  const res = await fetch(`${BASE_URL}/evaluation/${sessionId}?scope=${scope}`, { headers: authHeaders() })
  return res.json()
}

export async function getStats(sessionId) {
  const res = await fetch(`${BASE_URL}/evaluation/${sessionId}/stats`, { headers: authHeaders() })
  return res.json()
}
