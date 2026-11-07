<script setup>
import { computed, ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { marked } from 'marked'
import 'highlight.js/styles/atom-one-dark.css'

const props = defineProps({
  content: String,
  isStreaming: Boolean,
})

// ── 语法高亮：highlight.js ──
// 注意：marked v12 已移除 `highlight` 选项（在 marked 12.0.2 源码里搜不到该选项，
// 传进去是死代码），因此改为「渲染完成后对 DOM 调用 hljs.highlightElement」。
let hljs = null

async function ensureHljs() {
  if (hljs) return
  try {
    hljs = await import('highlight.js')
  } catch { /* 不可用时静默降级 */ }
}

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

const renderedHtml = computed(() => {
  const src = stabilizeMarkdown(renderContent.value)
  if (!src) return ''
  try {
    return marked.parse(src)
  } catch {
    return src
  }
})

// ── 流式期间节流渲染 ──
// 后端每来一个 SSE chunk 就改一次 content。直接拿去 parse 会有两个后果：
//   1) 每秒几十次全量 marked.parse + v-html 整体替换 innerHTML，整棵 DOM 反复重建；
//   2) 生成到一半时 markdown 是残缺的（``` 开了没闭、表格分隔行还没到），
//      解析结果会在「代码块 / 普通段落」「表格 / 纯文本」之间反复横跳，
//      高度忽大忽小 → 画面一抖一抖。
// 所以流式期间合并到 ~60ms 更新一次，并在渲染前把明显未闭合的围栏补上。
const THROTTLE_MS = 60
const renderContent = ref(props.content || '')
let pendingContent = props.content || ''
let flushTimer = null

// 把残缺的 markdown 补成能稳定解析的形态（只在流式期间生效）
function stabilizeMarkdown(text) {
  if (!props.isStreaming) return text
  const fences = (text.match(/^```/gm) || []).length
  if (fences % 2 === 1) return text + '\n```'
  return text
}

function flushNow() {
  if (flushTimer) {
    clearTimeout(flushTimer)
    flushTimer = null
  }
  renderContent.value = pendingContent
}

// ── 代码块后处理：语言标签 + 语法高亮 + 复制按钮 ──
const containerRef = ref(null)

function decorateCodeBlocks() {
  if (!containerRef.value) return
  const blocks = containerRef.value.querySelectorAll('pre')
  blocks.forEach(pre => {
    const codeEl = pre.querySelector('code')

    // 1) 语言标签（CSS 用 `pre::before { content: attr(data-lang) }` 展示）
    if (codeEl && !pre.dataset.lang) {
      const langClass = [...codeEl.classList].find(c => c.startsWith('language-'))
      pre.dataset.lang = langClass ? langClass.replace('language-', '') : ''
    }

    // 2) 语法高亮（渲染后按 DOM 处理，替代 marked v12 已移除的 highlight 回调）
    if (hljs && codeEl && !codeEl.dataset.highlighted) {
      try {
        hljs.default.highlightElement(codeEl)
      } catch { /* 高亮失败不影响展示 */ }
    }

    // 3) 复制按钮
    if (pre.querySelector('.code-copy-btn')) return
    const btn = document.createElement('button')
    btn.className = 'code-copy-btn'
    btn.textContent = '📋'
    btn.title = '复制代码'
    btn.addEventListener('click', () => {
      const code = pre.querySelector('code')?.textContent || pre.textContent || ''
      navigator.clipboard.writeText(code).then(() => {
        btn.textContent = '✅'
        setTimeout(() => { btn.textContent = '📋' }, 1500)
      }).catch(() => {
        btn.textContent = '❌'
        setTimeout(() => { btn.textContent = '📋' }, 1500)
      })
    })
    pre.style.position = 'relative'
    pre.appendChild(btn)
  })
}

onMounted(async () => {
  await ensureHljs()
  if (!props.isStreaming) {
    nextTick(() => decorateCodeBlocks())
  }
})

// 内容变化：流式时节流合并，非流式时立即跟上
watch(() => props.content, (val) => {
  pendingContent = val || ''
  if (!props.isStreaming) {
    renderContent.value = pendingContent
    return
  }
  if (flushTimer) return
  flushTimer = setTimeout(() => {
    flushTimer = null
    renderContent.value = pendingContent
  }, THROTTLE_MS)
})

// 流式结束：立刻补上最后一段，再做代码块后处理（语言标签 / 高亮 / 复制按钮）
watch(() => props.isStreaming, async (streaming) => {
  if (!streaming) {
    flushNow()
    await ensureHljs()
    nextTick(() => setTimeout(decorateCodeBlocks, 100))
  }
})

// 组件卸载时清掉待执行的节流定时器，避免对已销毁的 DOM 做后处理
onBeforeUnmount(() => {
  if (flushTimer) {
    clearTimeout(flushTimer)
    flushTimer = null
  }
})
</script>

<template>
  <div ref="containerRef" class="markdown-card" :class="{ streaming: isStreaming }">
    <div class="markdown-body" v-html="renderedHtml"></div>
    <span v-if="isStreaming" class="streaming-dot">●</span>
  </div>
</template>

<style>
/* ── 全局样式 — marked 生成的 HTML ── */
.markdown-body {
  line-height: 1.8;
  color: var(--text-primary);
  word-break: break-word;
}

.markdown-body h1 { font-size: 1.4em; font-weight: 700; margin: 1em 0 0.5em; }
.markdown-body h2 { font-size: 1.2em; font-weight: 600; margin: 0.8em 0 0.4em; padding-bottom: 4px; border-bottom: 1px solid var(--border-color); }
.markdown-body h3 { font-size: 1.05em; font-weight: 600; margin: 0.6em 0 0.3em; }

.markdown-body p { margin: 0.5em 0; }
.markdown-body strong { font-weight: 600; }
.markdown-body em { font-style: italic; }

/* 内联代码 */
.markdown-body code {
  background: var(--bg-code, #f1f5f9);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: 'Fira Code', 'Consolas', 'Courier New', monospace;
  color: #e83e8c;
}

/* 代码块容器 */
.markdown-body pre {
  background: #1e1e2e;
  border-radius: 10px;
  padding: 14px 16px;
  overflow-x: auto;
  margin: 12px 0;
  position: relative;
  border: 1px solid #2a2a3e;
}

.markdown-body pre code {
  background: transparent;
  color: #cdd6f4;
  padding: 0;
  font-size: 0.85em;
  line-height: 1.65;
  font-family: 'Fira Code', 'Consolas', 'Courier New', monospace;
}

/* 代码块顶部语言标签 */
.markdown-body pre::before {
  content: attr(data-lang);
  position: absolute;
  top: 0;
  right: 40px;
  font-size: 10px;
  color: #6c7086;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 6px;
}

/* 复制按钮 */
.code-copy-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  background: #2a2a3e;
  border: 1px solid #3e3e56;
  color: #cdd6f4;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 13px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  z-index: 1;
}
.markdown-body pre:hover .code-copy-btn {
  opacity: 1;
}
.code-copy-btn:hover {
  background: #3e3e56;
}

/* ── 引用块 ── */
.markdown-body blockquote {
  border-left: 3px solid var(--accent-color);
  padding: 8px 14px;
  margin: 10px 0;
  background: var(--accent-light);
  border-radius: 0 6px 6px 0;
  color: var(--text-secondary);
}

/* ── 列表 ── */
.markdown-body ul, .markdown-body ol {
  padding-left: 1.5em;
  margin: 6px 0;
}
.markdown-body li { margin: 2px 0; }

/* ── 表格 ── */
.markdown-body table {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
  font-size: 0.9em;
}
.markdown-body th, .markdown-body td {
  border: 1px solid var(--border-color);
  padding: 8px 12px;
  text-align: left;
}
.markdown-body th {
  background: var(--bg-hover);
  font-weight: 600;
}

/* ── 链接、分割线、图片 ── */
.markdown-body a {
  color: var(--accent-color);
  text-decoration: none;
}
.markdown-body a:hover { text-decoration: underline; }
.markdown-body hr {
  border: none;
  border-top: 1px solid var(--border-color);
  margin: 16px 0;
}
.markdown-body img {
  max-width: 100%;
  border-radius: 6px;
}
</style>

<style scoped>
.markdown-card {
  position: relative;
  /* v-html 整体替换时，浏览器的滚动锚定（scroll anchoring）会为了"稳住视口"
     不断反向修正 scrollTop，内容高度一变就被拉扯 → 视觉抖动。
     这里关掉锚定，滚动位置统一交给 ChatContainer 管理。 */
  overflow-anchor: none;
}

.streaming-dot {
  display: inline-block;
  animation: blink 1s infinite;
  color: var(--accent-color);
  font-size: 14px;
  margin-left: 2px;
}

@keyframes blink {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}
</style>
