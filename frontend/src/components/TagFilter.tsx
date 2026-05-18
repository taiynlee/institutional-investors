interface TagFilterProps {
  allTags: string[]
  selected: string[]
  onChange: (tags: string[]) => void
}

export function TagFilter({ allTags, selected, onChange }: TagFilterProps) {
  const toggle = (tag: string) => {
    onChange(selected.includes(tag) ? selected.filter(t => t !== tag) : [...selected, tag])
  }
  return (
    <div className="flex flex-wrap gap-2 mb-6">
      <button
        onClick={() => onChange([])}
        className={`px-3 py-1 rounded-full text-sm transition-colors ${selected.length === 0 ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
      >
        全部
      </button>
      {allTags.map(tag => (
        <button
          key={tag}
          onClick={() => toggle(tag)}
          className={`px-3 py-1 rounded-full text-sm transition-colors ${selected.includes(tag) ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
        >
          {tag}
        </button>
      ))}
    </div>
  )
}
