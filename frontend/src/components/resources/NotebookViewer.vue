<script setup>
/**
 * NotebookViewer — 渲染 Jupyter Notebook (.ipynb) JSON
 *
 * 三种状态：
 * 1. 流式加载中 → 紫色 loader，隐藏裸 JSON
 * 2. 解析成功   → 交互式单元格（markdown cell + code cell）
 * 3. 解析失败   → 折叠显示原始 JSON
 */
import { computed, ref, onMounted, nextTick, watch } from 'vue'
import MarkdownCard from './MarkdownCard.vue'

// ── 代码高亮 ──
let hljs = null
const hljsReady = ref(false)
async function loadHljs() {
  if (hljs) return
  try {
    hljs = await import('highlight.js')
    hljsReady.value = true
  } catch {}
}
onMounted(() => loadHljs())

// 引入 highlight.js 主题（适配深色代码块）
import 'highlight.js/styles/atom-one-dark.css'

function highlightCode(code) {
  if (!hljs) return code
  try {
    return hljs.default.highlightAuto(code).value
  } catch {
    return code
  }
}

// 将每个 code cell 的源转为高亮 HTML（响应式：依赖 hljsReady）
const highlightedCells = computed(() => {
  return cells.value.map(cell => {
    if (cell.cell_type !== 'code') return null
    const src = Array.isArray(cell.source) ? cell.source.join('') : cell.source
    return hljsReady.value ? highlightCode(src) : src
  })
})

const props = defineProps({
  content: String,
  isStreaming: Boolean,
})

/**
 * 括号计数解析：从指定位置开始找匹配的 JSON 对象。
 * 不能简单 lastIndexOf('}')——Python 代码里的 dict/set 也含 } 会干扰。
 */
function braceParse(text, startPos) {
  let depth = 0, inString = false, escape = false
  for (let i = startPos; i < text.length; i++) {
    const ch = text[i]
    if (escape) { escape = false; continue }
    if (ch === '\\') { escape = true; continue }
    if (ch === '"') { inString = !inString; continue }
    if (inString) continue
    if (ch === '{') depth++
    else if (ch === '}') {
      depth--
      if (depth === 0) {
        try {
          const nb = JSON.parse(text.slice(startPos, i + 1))
          if (nb?.cells?.length) return nb
        } catch { return null }
      }
    }
  }
  return null
}

function extractNotebookJSON(text) {
  // 策略1: 全文直接解析（最常见——LLM 直接输出纯 JSON）
  try {
    const nb = JSON.parse(text.trim())
    if (nb?.cells?.length) return nb
  } catch {}

  // 策略2: 从第一个 { 开始括号计数
  const firstBrace = text.indexOf('{')
  if (firstBrace !== -1) {
    const result = braceParse(text, firstBrace)
    if (result) return result
  }

  // 策略3: 从 "cells" 关键词往前找 {，再计数
  const cellsIdx = text.indexOf('"cells"')
  if (cellsIdx !== -1) {
    // 往前找最近的 {
    const before = text.lastIndexOf('{', cellsIdx)
    if (before !== -1) {
      const result = braceParse(text, before)
      if (result) return result
    }
  }

  // 策略4: 去掉 markdown 代码块包裹 ```json ... ```
  const cleaned = text.replace(/^```(?:json)?\s*\n?/gm, '').replace(/```\s*$/gm, '')
  if (cleaned !== text) {
    return extractNotebookJSON(cleaned)  // 递归
  }

  return null
}

const notebook = computed(() => {
  if (!props.content) return null
  const result = extractNotebookJSON(props.content)
  return result
})

const cells = computed(() => notebook.value?.cells || [])

// 是否看起来像是 notebook JSON（即使还没解析成功）
const looksLikeNotebook = computed(() => {
  if (!props.content) return false
  const c = props.content.trim()
  return c.includes('"cells"') || c.includes('"cell_type"') || c.includes('"nbformat"')
})

function cellTypeLabel(type) {
  return type === 'code' ? '代码' : '讲解'
}
</script>

<template>
  <!-- 状态1: 流式加载中 — 显示骨架屏 -->
  <div v-if="isStreaming && looksLikeNotebook && !notebook" class="notebook-loading">
    <div class="nb-header">
      <span class="nb-title">💻 正在生成代码案例...</span>
      <span class="nb-badge">v2</span>
    </div>
    <div class="loading-body">
      <div class="loading-pulse">
        <span class="pulse-dot"></span>
        <span>AI 正在为你编写代码和讲解，请稍候</span>
      </div>
    </div>
  </div>

  <!-- 状态2: 解析成功 → 渲染单元格 -->
  <div v-else-if="notebook" class="notebook-viewer">
    <div class="nb-header">
      <span class="nb-title">{{ notebook.metadata?.title || '代码实操' }}</span>
      <span class="nb-badge">Notebook v2</span>
    </div>
    <div
      v-for="(cell, i) in cells"
      :key="i"
      class="nb-cell"
      :class="`cell-${cell.cell_type}`"
    >
      <div class="cell-toolbar">
        <span class="cell-type-badge">In [{{ i + 1 }}]</span>
        <span class="cell-type-label">{{ cellTypeLabel(cell.cell_type) }}</span>
      </div>
      <div class="cell-body">
        <!-- Markdown cell -->
        <template v-if="cell.cell_type === 'markdown'">
          <MarkdownCard
            :content="Array.isArray(cell.source) ? cell.source.join('') : cell.source"
            :is-streaming="false"
          />
        </template>
        <!-- Code cell -->
        <template v-else-if="cell.cell_type === 'code'">
          <pre class="code-block"><code v-html="highlightedCells[i]"></code></pre>
          <div v-if="cell.outputs && cell.outputs.length" class="cell-outputs">
            <div v-for="(out, oi) in cell.outputs" :key="oi" class="cell-output">
              <pre v-if="out.text" class="output-text">{{ Array.isArray(out.text) ? out.text.join('') : out.text }}</pre>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>

  <!-- 状态3: 流式结束但解析失败 → 折叠显示 JSON -->
  <div v-else-if="!isStreaming && looksLikeNotebook" class="raw-json-hint">
    <details>
      <summary>📋 查看原始数据（JSON 格式）</summary>
      <pre class="json-pre">{{ content }}</pre>
    </details>
  </div>

  <!-- 普通 Markdown → 回退 -->
  <MarkdownCard
    v-else
    :content="content"
    :is-streaming="isStreaming"
  />
</template>

<style scoped>
/* ====== 加载中 ====== */
.notebook-loading {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
  background: #fafbfc;
}

.loading-body {
  padding: 24px 16px;
  text-align: center;
}

.loading-pulse {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
  font-size: 13px;
}

.pulse-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #667eea;
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}

/* ====== 笔记本主体 ====== */
.notebook-viewer {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
  background: #fafbfc;
}

.nb-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
}

.nb-title {
  font-size: 14px;
  font-weight: 600;
  flex: 1;
}

.nb-badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(255,255,255,0.25);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.nb-cell {
  border-bottom: 1px solid var(--border-color);
}

.nb-cell:last-child {
  border-bottom: none;
}

.cell-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #f0f0f4;
  border-bottom: 1px solid #e8e8ec;
  font-size: 11px;
}

.cell-type-badge {
  color: var(--text-muted);
  font-family: monospace;
  font-weight: 600;
}

.cell-type-label {
  color: var(--text-secondary);
  font-size: 10px;
}

.cell-body {
  padding: 10px 16px;
}

.cell-code .cell-body {
  padding: 0;
}

.code-block {
  margin: 0;
  padding: 14px 18px;
  background: #1e1e2e;
  border-radius: 0;
  overflow-x: auto;
}

.code-block code {
  font-family: 'Fira Code', 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.65;
  color: #cdd6f4;
  white-space: pre-wrap;
  word-break: break-word;
}

.cell-outputs {
  border-top: 1px dashed #e0e0e0;
  padding: 8px 16px;
  background: #f8f8f8;
}

.output-text {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

/* ====== 裸 JSON 折叠 ====== */
.raw-json-hint {
  margin: 8px 0;
}

.raw-json-hint summary {
  font-size: 13px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 6px 0;
}

.json-pre {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 11px;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
}
</style>
