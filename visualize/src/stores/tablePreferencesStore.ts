import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type TablePreferencesState = {
  datasetQuery: string
  learnerQuery: string
  datasetVisibleColumns: string[]
  learnerVisibleColumns: string[]
  datasetColumnsCustomized: boolean
  learnerColumnsCustomized: boolean
  setDatasetQuery: (query: string) => void
  setLearnerQuery: (query: string) => void
  setDatasetVisibleColumns: (columns: string[]) => void
  setLearnerVisibleColumns: (columns: string[]) => void
}

export const useTablePreferencesStore = create<TablePreferencesState>()(
  persist(
    (set) => ({
      datasetQuery: '',
      learnerQuery: '',
      datasetVisibleColumns: [],
      learnerVisibleColumns: [],
      datasetColumnsCustomized: false,
      learnerColumnsCustomized: false,
      setDatasetQuery: (query) => set({ datasetQuery: query }),
      setLearnerQuery: (query) => set({ learnerQuery: query }),
      setDatasetVisibleColumns: (columns) => set({ datasetVisibleColumns: columns, datasetColumnsCustomized: true }),
      setLearnerVisibleColumns: (columns) => set({ learnerVisibleColumns: columns, learnerColumnsCustomized: true }),
    }),
    {
      name: 'graph-analysis-table-preferences-v4',
    }
  )
)
