<script setup>
import { computed, ref, onMounted } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  size: { type: Number, default: 220 },
})

const animProgress = ref(0)
onMounted(() => {
  // 入场动画
  let start = null
  function step(ts) {
    if (!start) start = ts
    const elapsed = ts - start
    animProgress.value = Math.min(1, elapsed / 600)
    if (animProgress.value < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
})

const labels = ['记忆', '理解', '应用', '分析', '评估', '创造']
const keys = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create']
const levels = [0, 25, 50, 75, 100]

const points = computed(() => {
  const cx = props.size / 2
  const cy = props.size / 2
  const r = props.size * 0.38
  const angleSlice = (Math.PI * 2) / 6

  return keys.map((key, i) => {
    const val = (props.data[key] || 0) * animProgress.value / 100
    const angle = angleSlice * i - Math.PI / 2
    return {
      x: cx + r * val * Math.cos(angle),
      y: cy + r * val * Math.sin(angle),
      labelX: cx + (r + 18) * Math.cos(angle),
      labelY: cy + (r + 18) * Math.sin(angle),
      label: labels[i],
      value: Math.round((props.data[key] || 0) * animProgress.value),
    }
  })
})

const polygonPoints = computed(() => {
  return points.value.map(p => `${p.x},${p.y}`).join(' ')
})

const cx = props.size / 2
const cy = props.size / 2
const maxR = props.size * 0.38
const angleSlice = (Math.PI * 2) / 6

function gridPoint(level, i) {
  const r = maxR * (level / 100)
  const angle = angleSlice * i - Math.PI / 2
  return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`
}

function gridPolygon(level) {
  return keys.map((_, i) => gridPoint(level, i)).join(' ')
}
</script>

<template>
  <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" class="radar-chart">
    <!-- 网格 -->
    <polygon
      v-for="level in levels.slice(1)"
      :key="level"
      :points="gridPolygon(level)"
      fill="none"
      stroke="var(--border-color)"
      stroke-width="0.8"
      opacity="0.6"
    />
    <!-- 轴线 -->
    <line
      v-for="(_, i) in keys"
      :key="'axis' + i"
      :x1="cx"
      :y1="cy"
      :x2="cx + maxR * Math.cos(angleSlice * i - Math.PI / 2)"
      :y2="cy + maxR * Math.sin(angleSlice * i - Math.PI / 2)"
      stroke="var(--border-color)"
      stroke-width="0.5"
      opacity="0.4"
    />
    <!-- 数据多边形填充 -->
    <polygon
      :points="polygonPoints"
      fill="var(--accent-color)"
      fill-opacity="0.15"
      stroke="var(--accent-color)"
      stroke-width="2"
      stroke-linejoin="round"
    />
    <!-- 数据点 -->
    <circle
      v-for="(p, i) in points"
      :key="'dot' + i"
      :cx="p.x"
      :cy="p.y"
      r="4"
      fill="var(--accent-color)"
      stroke="white"
      stroke-width="1.5"
    />
    <!-- 标签 -->
    <text
      v-for="(p, i) in points"
      :key="'lbl' + i"
      :x="p.labelX"
      :y="p.labelY"
      text-anchor="middle"
      dominant-baseline="central"
      fill="var(--text-secondary)"
      font-size="11"
      font-weight="500"
    >
      {{ p.label }} {{ p.value }}
    </text>
  </svg>
</template>

<style scoped>
.radar-chart {
  display: block;
  margin: 0 auto;
}
</style>
