<script setup>
import { computed, onMounted, ref } from 'vue'
import { useChatStore } from '../../stores/chat'
import { useProfileStore } from '../../stores/profile'
import { getStats } from '../../api'
import DimensionTag from './DimensionTag.vue'
import RadarChart from './RadarChart.vue'

const chatStore = useChatStore()
const profileStore = useProfileStore()
const p = computed(() => profileStore.profile)

// ── 学习数据（从 evaluation/stats API 获取）──
const stats = ref(null)
const statsLoading = ref(false)

onMounted(async () => {
  if (!chatStore.sessionId) return
  statsLoading.value = true
  try {
    stats.value = await getStats(chatStore.sessionId)
  } catch (e) {
    console.error('获取学习数据失败:', e)
  }
  statsLoading.value = false
})

// ── 知识基础：等级进度 ──
const LEVELS = ['零基础', '了解一点', '有一点基础', '有基础', '比较熟练']
const LEVEL_PCT = [10, 30, 50, 70, 92]  // 每个等级在进度条上的位置
const levelIndex = computed(() => {
  const idx = LEVELS.indexOf(p.value.knowledge_base.level)
  return idx >= 0 ? idx : 0
})
const levelPercent = computed(() => LEVEL_PCT[levelIndex.value] || 10)
const nextLevel = computed(() => {
  const idx = levelIndex.value
  return idx < LEVELS.length - 1 ? LEVELS[idx + 1] : ''
})

// ── 认知水平雷达图数据 ──
const cognitiveData = computed(() => p.value.cognitive_level)
const hasCognitiveData = computed(() => {
  const d = p.value.cognitive_level
  return (d.remember || 0) + (d.understand || 0) + (d.apply || 0) +
         (d.analyze || 0) + (d.evaluate || 0) + (d.create || 0) > 0
})

// ── 兴趣方向数组 ──
const interests = computed(() => {
  const dirs = p.value.interest_tendency.directions
  if (!dirs || dirs.length === 0) return ['待探索']
  return dirs
})

// ── 易错点 ──
const errorTopics = computed(() => {
  const topics = p.value.error_patterns.error_prone_topics
  if (!topics || topics.length === 0) return ['待积累']
  return topics
})

// ── 学习节奏 ──
const pacePercent = computed(() => {
  const min = p.value.learning_pace.avg_session_minutes || 0
  return Math.min(100, (min / 60) * 100) // 60分钟=满格
})
const streakDays = computed(() => p.value.learning_pace.streak_days || 0)

// ── 学习风格图标映射 ──
const styleIcon = computed(() => {
  const map = {
    '视频学习型': '🎬', '阅读文档型': '📖', '动手项目型': '🛠️', '刷题练习型': '✏️',
    'visual': '👁️', 'verbal': '📝', 'active': '🏃', 'reflective': '🤔',
  }
  return map[p.value.learning_style.type] || '📚'
})

// ── 学习目标图标 ──
const goalIcon = computed(() => {
  const map = {
    '通过考试': '📝', '找工作/面试': '💼', '做个人项目': '🚀', '提升技能': '📈', '学术研究': '🔬',
  }
  return map[p.value.learning_goal.primary] || '🎯'
})

// ── 学习数据（从 stats 计算）──
const totalLearningMinutes = computed(() => stats.value?.total_learning_minutes || 0)
const totalLearningHours = computed(() => (totalLearningMinutes.value / 60).toFixed(1))
const engagementPct = computed(() => Math.min(100, Math.round(totalLearningMinutes.value / 600 * 100)))
const quizAccuracy = computed(() => stats.value?.quiz_accuracy || 0)
const quizAttempts = computed(() => stats.value?.quiz_attempts || 0)
const dailyStreak = computed(() => stats.value?.daily_streak || 0)
const topicsCompleted = computed(() => stats.value?.topics_completed || 0)
const questionsAsked = computed(() => stats.value?.questions_asked || 0)
const resourcesConsumed = computed(() => stats.value?.resources_consumed || 0)

// 学习效率：完成 topic 数 / 学习小时
const efficiencyPct = computed(() => {
  const h = totalLearningMinutes.value / 60
  const t = topicsCompleted.value
  if (h <= 0 || t <= 0) return 0
  return Math.min(100, Math.round(t / h * 20))
})
const efficiencyLabel = computed(() => {
  if (efficiencyPct.value >= 70) return '高效'
  if (efficiencyPct.value >= 30) return '正常'
  if (efficiencyPct.value > 0) return '待提升'
  return '--'
})
</script>

<template>
  <div class="profile-panel">
    <!-- 头部 -->
    <div class="panel-header">
      <h3>🧠 学习画像</h3>
      <span class="confidence-badge" :class="{ high: profileStore.confidence > 0.5 }">
        🛜 {{ Math.round(profileStore.confidence * 100) }}%
      </span>
    </div>

    <!-- 知识基础：等级进度条 -->
    <div class="viz-card">
      <div class="viz-header">
        <span class="viz-icon">📊</span>
        <span class="viz-title">知识基础</span>
      </div>
      <div class="level-display">
        <div class="level-badge">{{ p.knowledge_base.level }}</div>
        <div class="level-arrow" v-if="nextLevel">→ {{ nextLevel }}</div>
      </div>
      <div class="progress-bar-track">
        <div class="progress-bar-fill" :style="{ width: `${levelPercent}%` }"></div>
        <div class="level-dots">
          <span v-for="lv in LEVELS" :key="lv" class="level-dot"
            :class="{ active: LEVELS.indexOf(lv) <= levelIndex }"
            :title="lv"
          ></span>
        </div>
      </div>
      <div class="known-tags" v-if="p.knowledge_base.known_concepts.length">
        <DimensionTag
          v-for="c in p.knowledge_base.known_concepts.slice(0, 6)"
          :key="c" :value="c" variant="level"
        />
        <span v-if="p.knowledge_base.known_concepts.length > 6" class="more-tag">
          +{{ p.knowledge_base.known_concepts.length - 6 }}
        </span>
      </div>
    </div>

    <!-- 认知水平：雷达图 -->
    <div class="viz-card">
      <div class="viz-header">
        <span class="viz-icon">📐</span>
        <span class="viz-title">认知水平</span>
        <span class="viz-sub">Bloom 六维</span>
      </div>
      <RadarChart v-if="hasCognitiveData" :data="cognitiveData" :size="240" />
      <div v-else class="empty-viz">
        <span class="empty-viz-icon">🔍</span>
        <p>尚未评估</p>
        <p class="empty-viz-hint">跟 AI 进行一次深度对话，系统会自动分析你的认知水平</p>
      </div>
    </div>

    <!-- 学习风格 + 学习目标 双栏 -->
    <div class="viz-row">
      <div class="viz-card half">
        <div class="viz-header">
          <span class="viz-icon">{{ styleIcon }}</span>
          <span class="viz-title">学习风格</span>
        </div>
        <DimensionTag :value="p.learning_style.type" variant="pace" />
      </div>
      <div class="viz-card half">
        <div class="viz-header">
          <span class="viz-icon">{{ goalIcon }}</span>
          <span class="viz-title">学习目标</span>
        </div>
        <div class="goal-main">{{ p.learning_goal.primary || '待确认' }}</div>
        <div class="goal-timeline" v-if="p.learning_goal.timeline">
          ⏰ {{ p.learning_goal.timeline }}
        </div>
      </div>
    </div>

    <!-- 学习节奏：迷你仪表盘 -->
    <div class="viz-card">
      <div class="viz-header">
        <span class="viz-icon">⏱️</span>
        <span class="viz-title">学习节奏</span>
        <span class="viz-sub" v-if="streakDays">🔥 连续 {{ streakDays }} 天</span>
      </div>
      <div class="pace-row">
        <div class="pace-item">
          <div class="pace-value">{{ p.learning_pace.avg_session_minutes || 0 }}<span class="pace-unit">分钟</span></div>
          <div class="pace-label">日均学习</div>
          <div class="mini-bar-track">
            <div class="mini-bar-fill" :style="{ width: `${pacePercent}%` }"></div>
          </div>
        </div>
        <div class="pace-divider"></div>
        <div class="pace-item">
          <div class="pace-value">{{ p.learning_pace.completion_speed || '未知' }}</div>
          <div class="pace-label">推进速度</div>
        </div>
        <div class="pace-divider"></div>
        <div class="pace-item">
          <div class="pace-value">{{ streakDays }}<span class="pace-unit">天</span></div>
          <div class="pace-label">连续学习</div>
          <span class="streak-flame" v-if="streakDays >= 3">🔥</span>
          <span class="streak-flame" v-else-if="streakDays >= 1">✨</span>
        </div>
      </div>
      <div class="pace-note">推进速度＝平均每天完成的主题数；学习投入度＝累计学习时长，两者口径不同</div>
    </div>

    <!-- 学习数据：投入度 / 正确率 / 效率 -->
    <div class="viz-card">
      <div class="viz-header">
        <span class="viz-icon">📈</span>
        <span class="viz-title">学习数据</span>
        <span class="viz-sub" v-if="totalLearningMinutes > 0">累计 {{ totalLearningHours }}h</span>
      </div>

      <div v-if="statsLoading" class="empty-viz"><p>加载中...</p></div>

      <template v-else>
        <!-- 学习投入度 -->
        <div class="metric-row">
          <div class="metric-label">
            <span>📝 学习投入度</span>
            <span class="metric-pct">{{ engagementPct }}%</span>
          </div>
          <div class="metric-bar-track">
            <div class="metric-bar-fill engagement" :style="{ width: `${engagementPct}%` }"></div>
          </div>
          <div class="metric-hint">累计 {{ totalLearningMinutes }} 分钟（10小时=满格）</div>
        </div>

        <!-- 练习正确率 -->
        <div class="metric-row">
          <div class="metric-label">
            <span>🎯 练习正确率</span>
            <span class="metric-pct" :class="{ low: quizAccuracy < 60 }">{{ quizAccuracy }}%</span>
          </div>
          <div class="metric-bar-track">
            <div class="metric-bar-fill accuracy" :style="{ width: `${quizAccuracy}%` }"></div>
          </div>
          <div class="metric-hint">{{ quizAttempts }} 次练习{{ quizAttempts === 0 ? '，尚未练习' : '' }}</div>
        </div>

        <!-- 学习效率 -->
        <div class="metric-row">
          <div class="metric-label">
            <span>⚡ 学习效率</span>
            <span class="metric-pct">{{ efficiencyPct }}%</span>
            <span class="efficiency-tag" :class="efficiencyLabel">{{ efficiencyLabel }}</span>
          </div>
          <div class="metric-bar-track">
            <div class="metric-bar-fill efficiency" :style="{ width: `${efficiencyPct}%` }"></div>
          </div>
          <div class="metric-hint">{{ topicsCompleted }} 个主题 / {{ totalLearningHours }}h</div>
        </div>

        <!-- 迷你数据面板 -->
        <div class="stats-mini-row">
          <div class="stats-mini-item">
            <span class="stats-mini-val">{{ dailyStreak }}</span>
            <span class="stats-mini-lbl">连续天数</span>
          </div>
          <div class="stats-mini-item">
            <span class="stats-mini-val">{{ questionsAsked }}</span>
            <span class="stats-mini-lbl">提问次数</span>
          </div>
          <div class="stats-mini-item">
            <span class="stats-mini-val">{{ resourcesConsumed }}</span>
            <span class="stats-mini-lbl">学习资源</span>
          </div>
          <div class="stats-mini-item">
            <span class="stats-mini-val">{{ topicsCompleted }}</span>
            <span class="stats-mini-lbl">完成主题</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 兴趣方向 + 易错点 双栏 -->
    <div class="viz-row">
      <div class="viz-card half">
        <div class="viz-header">
          <span class="viz-icon">💡</span>
          <span class="viz-title">兴趣方向</span>
        </div>
        <div class="tag-cluster">
          <DimensionTag
            v-for="d in interests" :key="d"
            :value="d" variant="interest"
          />
        </div>
      </div>
      <div class="viz-card half">
        <div class="viz-header">
          <span class="viz-icon">⚠️</span>
          <span class="viz-title">易错点</span>
        </div>
        <div class="tag-cluster">
          <DimensionTag
            v-for="e in errorTopics" :key="e"
            :value="e" variant="error"
          />
        </div>
      </div>
    </div>

    <!-- 最后更新 -->
    <div v-if="profileStore.lastUpdated" class="last-updated">
      最后更新: {{ profileStore.lastUpdated }}
    </div>
  </div>
</template>

<style scoped>
.profile-panel { padding: 4px; }

/* ── 头部 ── */
.panel-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px;
}
.panel-header h3 {
  font-size: 17px; color: var(--text-primary); margin: 0; font-weight: 700;
}
.confidence-badge {
  font-size: 11px; padding: 3px 10px; border-radius: 10px;
  background: var(--bg-hover); color: var(--text-muted);
  font-weight: 500;
}
.confidence-badge.high {
  background: #e8f5e9; color: #2e7d32;
}

/* ── 通用卡片 ── */
.viz-card {
  border: 1px solid var(--border-color); border-radius: 10px;
  padding: 14px; margin-bottom: 10px;
  background: var(--bg-primary);
}
.viz-header {
  display: flex; align-items: center; gap: 6px; margin-bottom: 10px;
}
.viz-icon { font-size: 16px; }
.viz-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.viz-sub { font-size: 11px; color: var(--text-muted); margin-left: auto; }

.viz-row { display: flex; gap: 10px; }
.viz-row .half { flex: 1; min-width: 0; }

/* ── 等级进度条 ── */
.level-display {
  display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
}
.level-badge {
  font-size: 20px; font-weight: 800; color: #2e7d32;
  background: #e8f5e9; padding: 4px 14px; border-radius: 8px;
}
.level-arrow {
  font-size: 12px; color: var(--text-muted);
}
.progress-bar-track {
  position: relative; height: 6px; background: var(--bg-hover);
  border-radius: 3px; margin-bottom: 10px;
}
.progress-bar-fill {
  height: 100%; background: linear-gradient(90deg, #66bb6a, #2e7d32);
  border-radius: 3px; transition: width 0.6s ease;
}
.level-dots {
  position: absolute; top: -4px; left: 0; right: 0;
  display: flex; justify-content: space-between;
}
.level-dot {
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--bg-hover); border: 2px solid var(--border-color);
  transition: all 0.3s;
}
.level-dot.active {
  background: #2e7d32; border-color: #2e7d32; box-shadow: 0 0 0 3px rgba(46,125,50,.2);
}
.known-tags {
  display: flex; flex-wrap: wrap; gap: 4px; margin-top: 10px;
}
.more-tag {
  font-size: 11px; color: var(--text-muted); align-self: center;
}

/* ── 节奏行 ── */
.pace-row {
  display: flex; align-items: center; justify-content: space-around;
}
.pace-item { text-align: center; }
.pace-value {
  font-size: 22px; font-weight: 700; color: var(--text-primary); line-height: 1.2;
}
.pace-unit { font-size: 12px; font-weight: 400; color: var(--text-muted); }
.pace-label { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.pace-divider { width: 1px; height: 36px; background: var(--border-color); }
.mini-bar-track {
  width: 60px; height: 3px; background: var(--bg-hover);
  border-radius: 2px; margin: 4px auto 0;
}
.mini-bar-fill {
  height: 100%; background: #7b1fa2;
  border-radius: 2px; transition: width 0.6s ease;
}
.streak-flame { font-size: 14px; }
.pace-note {
  font-size: 11px; color: var(--text-muted);
  margin-top: 10px; padding-top: 8px;
  border-top: 1px dashed var(--border-color);
  line-height: 1.5;
}

/* ── 目标 ── */
.goal-main {
  font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px;
}
.goal-timeline { font-size: 12px; color: var(--text-muted); }

/* ── 标签簇 ── */
.tag-cluster {
  display: flex; flex-wrap: wrap; gap: 4px;
}

/* ── 底部 ── */
.last-updated {
  font-size: 11px; color: var(--text-muted); margin-top: 8px; text-align: center;
}

/* ── 学习数据度量条 ── */
.metric-row {
  margin-bottom: 12px;
}
.metric-label {
  display: flex; align-items: center; gap: 8px; margin-bottom: 4px;
  font-size: 13px; font-weight: 500; color: var(--text-primary);
}
.metric-pct {
  font-weight: 700; font-size: 14px; color: var(--accent-color); margin-left: auto;
}
.metric-pct.low { color: #e53935; }
.metric-bar-track {
  height: 6px; background: var(--bg-hover); border-radius: 3px; overflow: hidden;
}
.metric-bar-fill {
  height: 100%; border-radius: 3px; transition: width 0.8s ease;
}
.metric-bar-fill.engagement {
  background: linear-gradient(90deg, #42a5f5, #1e88e5);
}
.metric-bar-fill.accuracy {
  background: linear-gradient(90deg, #ffa726, #ef6c00);
}
.metric-bar-fill.efficiency {
  background: linear-gradient(90deg, #ab47bc, #7b1fa2);
}
.metric-hint {
  font-size: 11px; color: var(--text-muted); margin-top: 2px;
}
.efficiency-tag {
  font-size: 11px; padding: 1px 8px; border-radius: 8px; font-weight: 600;
}
.efficiency-tag.高效 { background: #e8f5e9; color: #2e7d32; }
.efficiency-tag.正常 { background: #fff3e0; color: #e65100; }
.efficiency-tag.待提升 { background: #fce4ec; color: #c62828; }

/* ── 迷你数据面板 ── */
.stats-mini-row {
  display: flex; justify-content: space-around;
  margin-top: 12px; padding-top: 10px;
  border-top: 1px solid var(--border-color);
}
.stats-mini-item {
  text-align: center;
}
.stats-mini-val {
  display: block; font-size: 18px; font-weight: 700; color: var(--text-primary);
}
.stats-mini-lbl {
  font-size: 10px; color: var(--text-muted);
}

/* ── 空状态 ── */
.empty-viz {
  text-align: center; padding: 20px 0; color: var(--text-muted);
}
.empty-viz-icon { font-size: 28px; }
.empty-viz p { margin: 4px 0; font-size: 13px; }
.empty-viz-hint { font-size: 11px; opacity: 0.7; }
</style>
