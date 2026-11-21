import { useEffect, useId, useRef, useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'

interface Props {
  vendors: [string, string][]
  selected: string
  onSelect: (vendor: string) => void
}

export default function InventoryVendorPicker({ vendors, selected, onSelect }: Props) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const label = vendors.find(([value]) => value === selected)?.[1]
  const names = new Map<string, number>()
  for (const [, name] of vendors) {
    const normalized = name.trim().toLocaleLowerCase()
    names.set(normalized, (names.get(normalized) ?? 0) + 1)
  }
  const options = vendors.filter(([value, name]) =>
    (name + ' ' + value).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))

  useEffect(() => {
    if (!open) return
    search.current?.focus()
    function outside(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  useEffect(() => {
    if (open) document.getElementById(id + '-option-' + active)?.scrollIntoView?.({ block: 'nearest' })
  }, [open, active, id])

  function choose(value: string) {
    onSelect(value)
    setOpen(false)
    trigger.current?.focus()
  }
  return <div className="inventory-vendor-picker" ref={root}
    onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false) }}>
    <label htmlFor={id}>Vendor</label>
    <button id={id} ref={trigger} type="button" aria-expanded={open} aria-haspopup="listbox"
      onClick={() => { setOpen(!open); setQuery(''); setActive(0) }}>
      <span>{label || 'Choose a vendor'}</span><ChevronDown size={16} />
    </button>
    {open && <div className="inventory-vendor-menu">
      <div className="inventory-vendor-search"><Search size={16} /><input ref={search} role="combobox"
        aria-label="Search vendors" aria-controls={id + '-list'} aria-expanded="true" aria-autocomplete="list"
        aria-activedescendant={options[active] ? id + '-option-' + active : undefined}
        placeholder="Search vendors…" value={query} onChange={e => { setQuery(e.target.value); setActive(0) }}
        onKeyDown={e => {
          if (e.key === 'Escape') { e.preventDefault(); setOpen(false); trigger.current?.focus() }
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            setActive(n => Math.max(0, Math.min(options.length - 1, n + (e.key === 'ArrowDown' ? 1 : -1))))
          }
          if (e.key === 'Enter' && options[active]) { e.preventDefault(); choose(options[active][0]) }
        }} /></div>
      <div id={id + '-list'} role="listbox" aria-label="Vendors" className="inventory-vendor-list">
        {options.map(([value, name], i) => <div key={value} id={id + '-option-' + i} role="option"
          aria-selected={value === selected} data-active={i === active} onMouseDown={e => e.preventDefault()}
          onClick={() => choose(value)}>
          <span>{name}{(names.get(name.trim().toLocaleLowerCase()) ?? 0) > 1 && <small>Vendor ID · {value.slice(-8)}</small>}</span>
          {value === selected && <Check size={15} />}
        </div>)}
      </div>
      {!options.length && <p role="status">No matching vendors.</p>}
      {selected && <button type="button" className="inventory-vendor-clear" onClick={() => choose('')}>Clear selection</button>}
    </div>}
  </div>
}
