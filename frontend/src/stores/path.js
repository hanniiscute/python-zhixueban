import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePathStore = defineStore('path', () => {
  const phases = ref([])
  const recommendedNext = ref({})
  const recommendations = ref([])

  function setPath(data) {
    if (data.phases) phases.value = data.phases
    if (data.recommended_next) recommendedNext.value = data.recommended_next
  }

  function setRecommendations(data) {
    if (data.recommendations) recommendations.value = data.recommendations
  }

  return {
    phases,
    recommendedNext,
    recommendations,
    setPath,
    setRecommendations,
  }
})
