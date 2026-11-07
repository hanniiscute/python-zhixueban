// 登录态工具
//
// 后端签发的 token 格式：v1.<payload_base64url>.<hmac签名>
// payload 内容：<user_id>|<过期时间戳(秒)>
//
// 说明：前端拿不到签名密钥，无法验签（那是后端的事），但可以解出过期时间。
// 在进页面之前先自查一遍，避免 token 已过期还放用户进页面、接口全 401 导致白屏。

/** 解析 token 里的过期时间戳（秒）。解析失败返回 0。 */
export function parseTokenExpiry(token) {
  if (!token || !token.startsWith('v1.')) return 0
  const parts = token.split('.')
  if (parts.length !== 3) return 0
  try {
    const b64 = parts[1]
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const std = padded.replace(/-/g, '+').replace(/_/g, '/')
    // 手动解码 UTF-8，避免 atob 对中文 userId 报 InvalidCharacterError
    const bytes = Uint8Array.from(atob(std), (c) => c.charCodeAt(0))
    const payload = new TextDecoder().decode(bytes)
    const idx = payload.lastIndexOf('|')
    if (idx < 0) return 0
    return Number(payload.slice(idx + 1)) || 0
  } catch {
    return 0
  }
}

/** 当前是否有有效登录态（token 存在且未过期） */
export function isLoggedIn() {
  const token = localStorage.getItem('token')
  const userId = localStorage.getItem('userId')
  if (!token || !userId) return false
  const exp = parseTokenExpiry(token)
  // 解不出过期时间（比如旧格式 token）→ 不拦，交给后端判定
  if (!exp) return true
  return Date.now() / 1000 < exp
}

/** 清除全部登录相关本地数据（换账号/过期时用，防止串数据） */
export function clearAuth() {
  const keys = [
    'token', 'userId', 'displayName', 'sessionId',
    'learningTopic', 'learnDoneTopics', 'onboarding_done',
  ]
  keys.forEach((k) => localStorage.removeItem(k))
}
