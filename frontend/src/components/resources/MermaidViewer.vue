<script setup>
import { ref, watch, onMounted, computed } from 'vue'

const props = defineProps({
  code: String,
  isStreaming: Boolean,
})

const svgContent = ref('')
const error = ref('')
const zoom = ref(1)
const minZoom = 0.3
const maxZoom = 3
const step = 0.15

// mermaid.render 需要唯一的 DOM id：同一页有两张导图时固定 id 会互相覆盖
let renderSeq = 0

function extractMermaidCode(text) {
  const match = text?.match(/```mermaid\s*\n([\s\S]*?)```/)
  return match ? match[1].trim() : text || ''
}

// 统计节点数
const nodeCount = computed(() => {
  if (!props.code) return 0
  const lines = extractMermaidCode(props.code).split('\n')
  return lines.filter(l => l.trim() && !l.trim().startsWith('mindmap')).length
})

function zoomIn() { zoom.value = Math.min(zoom.value + step, maxZoom) }
function zoomOut() { zoom.value = Math.max(zoom.value - step, minZoom) }
function zoomReset() { zoom.value = 1 }

async function render() {
  if (!props.code || props.isStreaming) return
  error.value = ''

  try {
    const { default: mermaid } = await import('mermaid')
    mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      themeVariables: {
        primaryColor: '#e8f4fd',
        primaryTextColor: '#1e293b',
        primaryBorderColor: '#3b82f6',
        lineColor: '#94a3b8',
        secondaryColor: '#f0fdf4',
        tertiaryColor: '#fef3c7',
      },
      mindmap: {
        padding: 20,
        maxWidth: 600,
      },
    })

    const cleanCode = extractMermaidCode(props.code)
    if (!cleanCode) {
      error.value = '未找到有效的Mermaid代码'
      return
    }

    const { svg } = await mermaid.render(`mermaid-svg-${++renderSeq}`, cleanCode)
    svgContent.value = svg
    zoom.value = 1
  } catch (e) {
    error.value = `渲染失败: ${e.message}`
  }
}

watch(() => props.isStreaming, (val) => { if (!val) render() })
watch(() => props.code, () => { if (!props.isStreaming) render() })
onMounted(() => render())
</script>

<template>
  <div class="mm-viewer">
    <!-- 头部工具栏 -->
    <div class="mm-toolbar">
      <span class="mm-title">🧠 思维导图</span>
      <span v-if="nodeCount" class="mm-nodes">{{ nodeCount }} 个节点</span>
      <div class="mm-zoom-controls">
        <button class="mm-zoom-btn" @click="zoomOut" :disabled="zoom <= minZoom" title="缩小">−</button>
        <span class="mm-zoom-label">{{ Math.round(zoom * 100) }}%</span>
        <button class="mm-zoom-btn" @click="zoomIn" :disabled="zoom >= maxZoom" title="放大">+</button>
        <button class="mm-zoom-btn reset" @click="zoomReset" title="重置">↺</button>
      </div>
    </div>

    <!-- 状态 -->
    <div v-if="isStreaming" class="mm-loading">
      <div class="mm-pulse"></div>
      <span>正在生成思维导图...</span>
    </div>

    <div v-else-if="error" class="mm-error">
      <span class="mm-error-icon">⚠️</span>
      {{ error }}
    </div>

    <!-- SVG 渲染区 -->
    <div v-else-if="svgContent" class="mm-canvas">
      <div
        class="mm-svg-wrapper"
        :style="{
          transform: `scale(${zoom})`,
          transformOrigin: 'top center',
        }"
        v-html="svgContent"
      ></div>
    </div>

    <!-- 空状态 -->
    <div v-else class="mm-empty">
      <span class="mm-empty-icon">📋</span>
      <span>等待思维导图数据...</span>
    </div>

    <!-- 底部提示 -->
    <div v-if="svgContent && !isStreaming" class="mm-footer">
      <span>🖱️ 滚轮缩放 · 拖拽平移</span>
    </div>
  </div>
</template>

<style scoped>
.mm-viewer {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-primary);
  margin: 10px 0;
  overflow: hidden;
}

/* ── 工具栏 ── */
.mm-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-hover);
  flex-wrap: wrap;
}
.mm-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.mm-nodes {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 8px;
}
.mm-zoom-controls {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}
.mm-zoom-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 15px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.mm-zoom-btn:hover:not(:disabled) {
  background: var(--accent-light);
  border-color: var(--accent-color);
}
.mm-zoom-btn:disabled {
  opacity: 0.35;
  cursor: default;
}
.mm-zoom-btn.reset {
  font-size: 13px;
  margin-left: 4px;
}
.mm-zoom-label {
  font-size: 11px;
  color: var(--text-muted);
  min-width: 36px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* ── 状态 ── */
.mm-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: var(--accent-color);
  font-size: 14px;
}
.mm-pulse {
  width: 10px; height: 10px;
  border-radius: 50%;
  background: var(--accent-color);
  animation: mm-pulse 1s infinite;
}
@keyframes mm-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}
.mm-error {
  padding: 24px;
  color: var(--error-color, #dc2626);
  font-size: 13px;
  text-align: center;
}
.mm-error-icon { margin-right: 6px; }
.mm-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 30px;
  color: var(--text-muted);
  font-size: 13px;
}
.mm-empty-icon { font-size: 28px; }

/* ── SVG 画布 ── */
.mm-canvas {
  padding: 20px 16px;
  overflow: auto;
  max-height: 70vh;
  background: #fafbfc;
}
.mm-svg-wrapper {
  /* CSS transform 由 zoom 驱动 */
  transition: transform 0.15s ease;
}
.mm-svg-wrapper :deep(svg) {
  display: block;
  margin: 0 auto;
}

/* ── 底部 ── */
.mm-footer {
  padding: 6px 16px;
  border-top: 1px solid var(--border-color);
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  background: var(--bg-hover);
}
</style>
