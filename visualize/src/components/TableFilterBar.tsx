import { useState, type KeyboardEvent } from 'react'

function FilterTag({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex max-w-[min(100%,320px)] items-center gap-1 rounded-md border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-900 shadow-sm">
      <span className="min-w-0 truncate font-medium">{label}</span>
      <button
        type="button"
        className="ml-0.5 shrink-0 rounded px-1 leading-none text-sky-600 hover:bg-sky-100 hover:text-sky-950"
        aria-label={`移除筛选 ${label}`}
        onClick={onRemove}
      >
        ×
      </button>
    </span>
  )
}

type Props = {
  placeholder: string
  tags: string[]
  onAddTag: (tag: string) => void
  onRemoveTag: (tag: string) => void
  onClearAll: () => void
  /** 搜索输入框宽度类名，默认 w-72 */
  inputClassName?: string
}

export function TableFilterBar({
  placeholder,
  tags,
  onAddTag,
  onRemoveTag,
  onClearAll,
  inputClassName = 'w-72',
}: Props) {
  const [draft, setDraft] = useState('')

  const submit = () => {
    const t = draft.trim()
    if (!t) return
    onAddTag(t)
    setDraft('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="w-full space-y-2">
      <div className="flex w-full flex-wrap items-center gap-2">
        <input
          className={`input-base min-w-[12rem] flex-1 ${inputClassName}`}
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="button" className="btn-primary px-3 py-1.5 text-sm" onClick={submit}>
          筛选
        </button>
      </div>
      {tags.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/80 px-2 py-2">
          <span className="shrink-0 text-xs text-slate-500">已选筛选</span>
          {tags.map((tag) => (
            <FilterTag key={tag} label={tag} onRemove={() => onRemoveTag(tag)} />
          ))}
          <button
            type="button"
            className="shrink-0 text-xs text-slate-500 underline-offset-2 hover:text-slate-800 hover:underline"
            onClick={onClearAll}
          >
            清空全部
          </button>
        </div>
      )}
    </div>
  )
}

