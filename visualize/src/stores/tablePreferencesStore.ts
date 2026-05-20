import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type TablePreferencesState = {
  datasetFilterTags: string[]
  learnerFilterTags: string[]
  datasetVisibleColumns: string[]
  learnerVisibleColumns: string[]
  datasetColumnsCustomized: boolean
  learnerColumnsCustomized: boolean
  addDatasetFilterTag: (tag: string) => void
  removeDatasetFilterTag: (tag: string) => void
  clearDatasetFilterTags: () => void
  addLearnerFilterTag: (tag: string) => void
  removeLearnerFilterTag: (tag: string) => void
  clearLearnerFilterTags: () => void
  setDatasetVisibleColumns: (columns: string[]) => void
  setLearnerVisibleColumns: (columns: string[]) => void
}

function appendTag(tags: string[], raw: string): string[] {
  const t = raw.trim()
  if (!t || tags.includes(t)) return tags
  return [...tags, t]
}

export const useTablePreferencesStore = create<TablePreferencesState>()(
  persist(
    (set) => ({
      datasetFilterTags: [],
      learnerFilterTags: [],
      datasetVisibleColumns: [],
      learnerVisibleColumns: [],
      datasetColumnsCustomized: false,
      learnerColumnsCustomized: false,
      addDatasetFilterTag: (tag) =>
        set((s) => ({ datasetFilterTags: appendTag(s.datasetFilterTags, tag) })),
      removeDatasetFilterTag: (tag) =>
        set((s) => ({ datasetFilterTags: s.datasetFilterTags.filter((t) => t !== tag) })),
      clearDatasetFilterTags: () => set({ datasetFilterTags: [] }),
      addLearnerFilterTag: (tag) =>
        set((s) => ({ learnerFilterTags: appendTag(s.learnerFilterTags, tag) })),
      removeLearnerFilterTag: (tag) =>
        set((s) => ({ learnerFilterTags: s.learnerFilterTags.filter((t) => t !== tag) })),
      clearLearnerFilterTags: () => set({ learnerFilterTags: [] }),
      setDatasetVisibleColumns: (columns) => set({ datasetVisibleColumns: columns, datasetColumnsCustomized: true }),
      setLearnerVisibleColumns: (columns) => set({ learnerVisibleColumns: columns, learnerColumnsCustomized: true }),
    }),
    {
      name: 'graph-analysis-table-preferences-v5',
      version: 5,
      migrate: (persisted) => {
        const p = persisted as Record<string, unknown>
        const next = { ...p }
        if (!Array.isArray(next.datasetFilterTags)) {
          const q = typeof next.datasetQuery === 'string' ? next.datasetQuery.trim() : ''
          next.datasetFilterTags = q ? [q] : []
        }
        if (!Array.isArray(next.learnerFilterTags)) {
          const q = typeof next.learnerQuery === 'string' ? next.learnerQuery.trim() : ''
          next.learnerFilterTags = q ? [q] : []
        }
        delete next.datasetQuery
        delete next.learnerQuery
        return next as TablePreferencesState
      },
    },
  ),
)
